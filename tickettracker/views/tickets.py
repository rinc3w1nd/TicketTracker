"""Ticket management views."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from sqlalchemy import or_
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from ..config import AppConfig
from ..extensions import db
from ..models import Attachment, Tag, Ticket, TicketUpdate


tickets_bp = Blueprint("tickets", __name__)


def _app_config() -> AppConfig:
    return current_app.config["APP_CONFIG"]


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        # HTML datetime-local uses "YYYY-MM-DDTHH:MM"
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _compute_ticket_color(ticket: Ticket, config: AppConfig) -> str:
    status_palette: Dict[str, str] = {}
    for key, value in config.colors.statuses.items():
        lowered = (key or "").lower()
        if not lowered:
            continue
        status_palette[lowered] = value
        status_palette[lowered.replace(" ", "_")] = value

    now = datetime.utcnow()
    status_lower = (ticket.status or "").lower()
    status_color = status_palette.get(status_lower) or status_palette.get(status_lower.replace(" ", "_"))
    if status_color:
        return status_color

    overdue_color = config.colors.gradient_overdue_color()

    if ticket.due_date:
        seconds_remaining = (ticket.due_date - now).total_seconds()
        if seconds_remaining <= 0:
            return overdue_color
        days_remaining = seconds_remaining / 86400
        thresholds = config.sla.due_thresholds()
        if not thresholds:
            return config.colors.gradient_stage_color(0)
        for index, threshold in enumerate(thresholds):
            if days_remaining > threshold:
                return config.colors.gradient_stage_color(index)
        return config.colors.gradient_stage_color(len(thresholds) - 1)

    reference_date = ticket.age_reference_date or (
        ticket.created_at.date() if ticket.created_at else now.date()
    )
    reference_datetime = datetime.combine(reference_date, datetime.min.time())
    age_days = max(0.0, (now - reference_datetime).total_seconds() / 86400)
    thresholds = config.sla.priority_thresholds(ticket.priority or "")
    if thresholds:
        for index, threshold in enumerate(thresholds):
            if age_days <= threshold:
                return config.colors.gradient_stage_color(index)
    else:
        return config.colors.gradient_stage_color(0)

    return overdue_color


def _compute_ticket_tint(color: str, intensity: float = 0.25) -> str:
    """Return a translucent tint for the provided hex color."""

    if not color:
        return f"rgba(56, 189, 248, {intensity:.2f})"

    color = color.strip()
    if color.startswith("#"):
        hex_value = color.lstrip("#")
        if len(hex_value) == 3:
            hex_value = "".join(component * 2 for component in hex_value)
        if len(hex_value) == 6:
            try:
                red = int(hex_value[0:2], 16)
                green = int(hex_value[2:4], 16)
                blue = int(hex_value[4:6], 16)
            except ValueError:
                pass
            else:
                return f"rgba({red}, {green}, {blue}, {intensity:.2f})"

    percent = round(intensity * 100)
    return f"color-mix(in srgb, {color} {percent}%, transparent)"


def _is_compact_mode() -> bool:
    """Return ``True`` when the current request asks for compact mode."""

    value = request.args.get("compact")
    if value is None:
        return False
    return value.lower() in {"1", "true", "yes", "on"}


def _build_compact_toggle_url(endpoint: str, compact_mode: bool, **values: object) -> str:
    """Return a URL that toggles the compact flag while preserving filters."""

    query_args: Dict[str, List[str]] = {key: list(items) for key, items in request.args.lists()}
    if compact_mode:
        query_args.pop("compact", None)
    else:
        query_args["compact"] = ["1"]

    flattened: Dict[str, object] = {
        key: value if len(value) != 1 else value[0]
        for key, value in query_args.items()
    }
    return url_for(endpoint, **values, **flattened)


def _parse_tags(raw_tags: str | None) -> List[str]:
    if not raw_tags:
        return []
    return [tag.strip() for tag in raw_tags.replace(";", ",").split(",") if tag.strip()]


def _store_attachments(
    files: Iterable[FileStorage], ticket: Ticket, update: TicketUpdate | None = None
) -> List[Attachment]:
    stored: List[Attachment] = []
    upload_root = Path(current_app.config["UPLOAD_FOLDER"])
    ticket_folder = upload_root / str(ticket.id)
    ticket_folder.mkdir(parents=True, exist_ok=True)

    for upload in files:
        if not upload or not upload.filename:
            continue
        original_name = upload.filename
        safe_name = secure_filename(original_name) or "attachment"
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
        stored_name = f"{timestamp}_{safe_name}"
        target_path = ticket_folder / stored_name
        upload.save(target_path)

        attachment = Attachment(
            ticket=ticket,
            update=update,
            original_filename=original_name,
            stored_filename=f"{ticket.id}/{stored_name}",
            mimetype=upload.mimetype,
            size=target_path.stat().st_size if target_path.exists() else None,
        )
        db.session.add(attachment)
        stored.append(attachment)
    return stored


@tickets_bp.route("/")
def list_tickets():
    config = _app_config()
    query = Ticket.query

    compact_mode = _is_compact_mode()

    status_filter = request.args.get("status")
    if status_filter:
        query = query.filter(Ticket.status == status_filter)

    priority_filter = request.args.get("priority")
    if priority_filter:
        query = query.filter(Ticket.priority == priority_filter)

    tag_filters = request.args.getlist("tag")
    if tag_filters:
        tag_mode = request.args.get("tag_mode", "any")
        if tag_mode == "all":
            for tag_name in tag_filters:
                query = query.filter(Ticket.tags.any(Tag.name == tag_name))
        else:
            query = query.filter(Ticket.tags.any(Tag.name.in_(tag_filters)))

    search_term = request.args.get("q")
    if search_term:
        like_term = f"%{search_term}%"
        query = query.outerjoin(Ticket.tags).filter(
            or_(
                Ticket.title.ilike(like_term),
                Ticket.description.ilike(like_term),
                Ticket.notes.ilike(like_term),
                Ticket.links.ilike(like_term),
                Ticket.requester.ilike(like_term),
                Ticket._watchers.ilike(like_term),
                Tag.name.ilike(like_term),
            )
        ).distinct()

    sort = request.args.get("sort", "due")
    valid_sorts = {"due", "priority", "updated", "created"}
    if sort not in valid_sorts:
        sort = "due"

    default_orders = {"due": "asc", "priority": "asc", "updated": "desc", "created": "desc"}
    requested_order = request.args.get("order")
    order = requested_order if requested_order in {"asc", "desc"} else default_orders[sort]

    if sort == "priority":
        priority_mappings = [
            (priority, index) for index, priority in enumerate(config.priorities)
        ]
        priority_case = db.case(
            priority_mappings,
            value=Ticket.priority,
            else_=len(config.priorities),
        )
        if order == "desc":
            query = query.order_by(
                priority_case.desc(),
                Ticket.due_date.is_(None),
                Ticket.due_date.asc(),
                Ticket.updated_at.desc(),
            )
        else:
            query = query.order_by(
                priority_case,
                Ticket.due_date.is_(None),
                Ticket.due_date.asc(),
                Ticket.updated_at.desc(),
            )
    elif sort == "updated":
        if order == "asc":
            query = query.order_by(Ticket.updated_at.asc())
        else:
            query = query.order_by(Ticket.updated_at.desc())
    elif sort == "created":
        if order == "asc":
            query = query.order_by(Ticket.created_at.asc())
        else:
            query = query.order_by(Ticket.created_at.desc())
    else:
        due_order = Ticket.due_date.desc() if order == "desc" else Ticket.due_date.asc()
        priority_order = Ticket.priority.desc() if order == "desc" else Ticket.priority.asc()
        query = query.order_by(Ticket.due_date.is_(None), due_order, priority_order)

    tickets = query.all()
    for ticket in tickets:
        ticket.display_color = _compute_ticket_color(ticket, config)  # type: ignore[attr-defined]
        ticket.tint_color = _compute_ticket_tint(ticket.display_color)  # type: ignore[attr-defined]

    available_tags = Tag.query.order_by(Tag.name).all()

    return render_template(
        "index.html",
        tickets=tickets,
        config=config,
        available_tags=available_tags,
        priorities=config.priorities,
        compact_mode=compact_mode,
        compact_toggle_url=_build_compact_toggle_url(
            "tickets.list_tickets", compact_mode
        ),
        filters={
            "status": status_filter,
            "priority": priority_filter,
            "tags": tag_filters,
            "tag_mode": request.args.get("tag_mode", "any"),
            "search": search_term,
            "sort": sort,
            "order": order,
            "has_active_filters": bool(
                status_filter
                or priority_filter
                or tag_filters
                or search_term
                or request.args.get("tag_mode") == "all"
            ),
        },
    )


@tickets_bp.route("/tickets/<int:ticket_id>")
def ticket_detail(ticket_id: int):
    config = _app_config()
    ticket = Ticket.query.get_or_404(ticket_id)
    compact_mode = _is_compact_mode()
    ticket.display_color = _compute_ticket_color(ticket, config)  # type: ignore[attr-defined]
    ticket.tint_color = _compute_ticket_tint(ticket.display_color)  # type: ignore[attr-defined]
    return render_template(
        "ticket_detail.html",
        ticket=ticket,
        config=config,
        priorities=config.priorities,
        hold_reasons=config.hold_reasons,
        compact_mode=compact_mode,
        compact_toggle_url=_build_compact_toggle_url(
            "tickets.ticket_detail", compact_mode, ticket_id=ticket.id
        ),
    )


@tickets_bp.route("/tickets/new", methods=["GET", "POST"])
def create_ticket():
    config = _app_config()
    compact_mode = _is_compact_mode()
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        if not title or not description:
            flash("Title and description are required.", "error")
            return redirect(request.url)

        ticket = Ticket(
            title=title,
            description=description,
            requester=request.form.get("requester") or None,
            priority=request.form.get("priority") or (config.priorities[0] if config.priorities else "Medium"),
            status=request.form.get("status") or (config.workflow[0] if config.workflow else "Open"),
            due_date=_parse_datetime(request.form.get("due_date")),
            notes=request.form.get("notes") or None,
            links=request.form.get("links") or None,
            on_hold_reason=request.form.get("on_hold_reason") or None,
        )
        ticket.watchers = request.form.get("watchers", "")
        db.session.add(ticket)
        ticket.set_tags(_parse_tags(request.form.get("tags")))
        ticket.add_update("Ticket created", is_system=True, status_to=ticket.status)
        if ticket.status != "On Hold":
            ticket.on_hold_reason = None
        db.session.flush()

        _store_attachments(request.files.getlist("attachments"), ticket)

        db.session.commit()
        flash("Ticket created", "success")
        return redirect(
            url_for(
                "tickets.ticket_detail",
                ticket_id=ticket.id,
                **({"compact": "1"} if compact_mode else {}),
            )
        )

    return render_template(
        "ticket_form.html",
        config=config,
        ticket=None,
        priorities=config.priorities,
        workflow=config.workflow,
        hold_reasons=config.hold_reasons,
        compact_mode=compact_mode,
        compact_toggle_url=_build_compact_toggle_url(
            "tickets.create_ticket", compact_mode
        ),
    )


@tickets_bp.route("/tickets/<int:ticket_id>/edit", methods=["GET", "POST"])
def edit_ticket(ticket_id: int):
    config = _app_config()
    ticket = Ticket.query.get_or_404(ticket_id)
    compact_mode = _is_compact_mode()

    if request.method == "POST":
        previous_status = ticket.status
        ticket.title = request.form.get("title", ticket.title)
        ticket.description = request.form.get("description", ticket.description)
        ticket.requester = request.form.get("requester") or None
        ticket.priority = request.form.get("priority") or ticket.priority
        ticket.status = request.form.get("status") or ticket.status
        ticket.due_date = _parse_datetime(request.form.get("due_date"))
        ticket.notes = request.form.get("notes") or None
        ticket.links = request.form.get("links") or None
        ticket.on_hold_reason = request.form.get("on_hold_reason") or None
        ticket.watchers = request.form.get("watchers", "")

        ticket.set_tags(_parse_tags(request.form.get("tags")))

        if ticket.status != previous_status:
            message = f"Status changed from {previous_status} to {ticket.status}"
            ticket.add_update(
                message,
                status_from=previous_status,
                status_to=ticket.status,
                is_system=True,
            )
            if ticket.status != "On Hold":
                ticket.on_hold_reason = None

        db.session.flush()
        _store_attachments(request.files.getlist("attachments"), ticket)
        db.session.commit()
        flash("Ticket updated", "success")
        return redirect(
            url_for(
                "tickets.ticket_detail",
                ticket_id=ticket.id,
                **({"compact": "1"} if compact_mode else {}),
            )
        )

    return render_template(
        "ticket_form.html",
        config=config,
        ticket=ticket,
        priorities=config.priorities,
        workflow=config.workflow,
        hold_reasons=config.hold_reasons,
        compact_mode=compact_mode,
        compact_toggle_url=_build_compact_toggle_url(
            "tickets.edit_ticket", compact_mode, ticket_id=ticket.id
        ),
    )


@tickets_bp.route("/tickets/<int:ticket_id>/updates", methods=["POST"])
def add_update(ticket_id: int):
    ticket = Ticket.query.get_or_404(ticket_id)
    compact_mode = _is_compact_mode()

    message = request.form.get("message", "").strip()
    author = request.form.get("author") or None
    new_status = request.form.get("status") or ticket.status
    hold_reason = request.form.get("on_hold_reason") or None
    raw_re_age = request.form.get("reage_ticket")
    re_age_requested = (raw_re_age or "").lower() in {"1", "true", "yes", "on"}

    previous_status = ticket.status
    if new_status != ticket.status:
        ticket.status = new_status
        ticket.on_hold_reason = hold_reason if new_status == "On Hold" else None
        status_message = f"Status changed from {previous_status} to {new_status}"
        ticket.add_update(status_message, status_from=previous_status, status_to=new_status, is_system=True)

    if message:
        update = ticket.add_update(message, author=author)
    else:
        update = None

    db.session.flush()
    if not ticket.due_date and re_age_requested:
        ticket.age_reference_date = datetime.utcnow().date()

    if update:
        _store_attachments(request.files.getlist("attachments"), ticket, update=update)
    else:
        _store_attachments(request.files.getlist("attachments"), ticket)

    db.session.commit()
    flash("Update added", "success")
    return redirect(
        url_for(
            "tickets.ticket_detail",
            ticket_id=ticket.id,
            **({"compact": "1"} if compact_mode else {}),
        )
    )


@tickets_bp.route("/attachments/<int:attachment_id>")
def download_attachment(attachment_id: int):
    attachment = Attachment.query.get_or_404(attachment_id)
    upload_root = Path(current_app.config["UPLOAD_FOLDER"])
    file_path = upload_root / attachment.stored_filename
    compact_mode = _is_compact_mode()
    if not file_path.exists():
        flash("Attachment no longer exists on disk.", "error")
        return redirect(
            url_for(
                "tickets.ticket_detail",
                ticket_id=attachment.ticket_id,
                **({"compact": "1"} if compact_mode else {}),
            )
        )

    return send_from_directory(
        directory=str(file_path.parent),
        path=file_path.name,
        as_attachment=True,
        download_name=attachment.original_filename,
        mimetype=attachment.mimetype or "application/octet-stream",
    )
