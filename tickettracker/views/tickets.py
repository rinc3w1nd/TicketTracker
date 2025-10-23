"""Ticket management views."""
from __future__ import annotations

import colorsys
import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List
from urllib.parse import urlparse

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
from sqlalchemy import case, or_
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from ..config import AppConfig
from ..extensions import db
from ..models import Attachment, Tag, Ticket, TicketUpdate
from ..summary import build_ticket_clipboard_summary
from ..utils.uploads import compute_stream_sha256, generate_uuid7


tickets_bp = Blueprint("tickets", __name__)


@tickets_bp.app_context_processor
def inject_ticket_helpers() -> Dict[str, object]:
    """Expose helper utilities used by ticket templates."""

    def tag_filter_url(tag_name: str, compact_value: str) -> str:
        """Return a ticket list URL that replaces the tag filter.

        The generated link preserves any existing query arguments (e.g. status,
        search terms) so the broader filter state remains intact. When no tag
        filter exists yet the helper ensures ``tag_mode`` defaults to ``"any"``
        so additional tags broaden the search rather than narrowing it
        unexpectedly.
        """

        query_args: Dict[str, List[str]] = {
            key: list(values) for key, values in request.args.lists()
        }
        query_args["tag"] = [tag_name]

        tag_mode = request.args.get("tag_mode") or "any"
        query_args["tag_mode"] = [tag_mode]
        query_args["compact"] = [compact_value]

        flattened: Dict[str, object] = {
            key: value if len(value) != 1 else value[0]
            for key, value in query_args.items()
        }
        return url_for("tickets.list_tickets", **flattened)

    return {"tag_filter_url": tag_filter_url}


BASE_TINT_INTENSITY = 0.5
# Overdue requests ask for a stronger overlay but remain capped inside the tint helper.
OVERDUE_TINT_INTENSITY = 0.75


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


def _build_status_palette(config: AppConfig) -> Dict[str, str]:
    palette: Dict[str, str] = {}
    for key, value in config.colors.statuses.items():
        normalized_key = (key or "").strip().lower()
        if not normalized_key or not value:
            continue
        palette[normalized_key] = value
        palette[normalized_key.replace(" ", "_")] = value
    return palette


def _resolve_status_color(status: str | None, palette: Dict[str, str]) -> str | None:
    normalized = (status or "").strip().lower()
    if not normalized:
        return None
    return palette.get(normalized) or palette.get(normalized.replace(" ", "_"))


def _compute_ticket_color(
    ticket: Ticket,
    config: AppConfig,
    status_palette: Dict[str, str] | None = None,
) -> str:
    palette = status_palette or _build_status_palette(config)

    now = datetime.utcnow()
    status_color = _resolve_status_color(ticket.status, palette)
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


def _compute_ticket_tint(
    color: str,
    intensity: float = BASE_TINT_INTENSITY,
    *,
    overdue: bool = False,
) -> str:
    """Return a translucent tint for the provided color.

    The default tint is intentionally bolder than before (50% opacity).
    Overdue tickets receive a saturated boost but never exceed 50%
    opacity so text remains readable.
    """

    max_opacity = 0.5
    normalized_intensity = max(0.0, min(1.0, intensity))
    if overdue:
        # Cap overdue fill at 50% but ensure we use the strongest overlay available.
        normalized_intensity = max_opacity
    else:
        normalized_intensity = min(max_opacity, normalized_intensity)

    def _format_rgba(red: int, green: int, blue: int) -> str:
        return f"rgba({red}, {green}, {blue}, {normalized_intensity:.2f})"

    if not color:
        base_rgb = (56, 189, 248)
    else:
        color = color.strip()
        base_rgb: tuple[int, int, int] | None = None
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
                    base_rgb = red, green, blue

        if base_rgb is not None:
            red, green, blue = base_rgb
            if overdue:
                red, green, blue = _boost_overdue_rgb(red, green, blue)
            return _format_rgba(red, green, blue)

        if not color.startswith("#"):
            percent = round(normalized_intensity * 100)
            if overdue:
                percent = max(percent, round(max_opacity * 100))
            return f"color-mix(in srgb, {color} {percent}%, transparent)"

        base_rgb = (56, 189, 248)

    if overdue:
        red, green, blue = _boost_overdue_rgb(*base_rgb)
        return _format_rgba(red, green, blue)

    red, green, blue = base_rgb
    return _format_rgba(red, green, blue)


def _compute_backlog_remaining_days(
    ticket: Ticket, config: AppConfig, now: datetime
) -> float | None:
    """Return days remaining for tickets managed by backlog SLA."""

    reference_date = ticket.age_reference_date or (
        ticket.created_at.date() if ticket.created_at else now.date()
    )
    reference_datetime = datetime.combine(reference_date, datetime.min.time())
    age_seconds = max(0.0, (now - reference_datetime).total_seconds())
    age_days = age_seconds / 86400
    return config.sla.remaining_days(ticket.priority or "", age_days=age_days)


def _format_sla_countdown(remaining_days: float) -> str:
    """Return a human-friendly countdown string for SLA tracking."""

    if math.isnan(remaining_days) or math.isinf(remaining_days):
        remaining_days = 0.0

    if remaining_days >= 0:
        prefix = "T-"
        day_count = max(0, math.ceil(remaining_days))
    else:
        prefix = "T+"
        day_count = math.ceil(abs(remaining_days))

    label = "Day" if day_count == 1 else "Days"
    return f"SLA : {prefix}{day_count} {label}"


def _annotate_ticket_sla(
    ticket: Ticket, config: AppConfig, now: datetime | None = None
) -> None:
    """Attach SLA countdown and overdue state metadata to the ticket."""

    current = now or datetime.utcnow()
    sla_countdown: str | None = None
    sla_remaining: float | None = None
    sla_breached = False

    if ticket.due_date:
        sla_breached = ticket.due_date <= current
    else:
        sla_remaining = _compute_backlog_remaining_days(ticket, config, current)
        if sla_remaining is not None:
            sla_breached = sla_remaining < 0
            sla_countdown = _format_sla_countdown(sla_remaining)

    ticket.is_overdue = sla_breached  # type: ignore[attr-defined]
    ticket.sla_remaining_days = sla_remaining  # type: ignore[attr-defined]
    ticket.sla_countdown = sla_countdown  # type: ignore[attr-defined]
    ticket.sla_is_breached = sla_breached  # type: ignore[attr-defined]

    tint_intensity = OVERDUE_TINT_INTENSITY if sla_breached else BASE_TINT_INTENSITY
    ticket.tint_color = _compute_ticket_tint(
        ticket.display_color,
        intensity=tint_intensity,
        overdue=sla_breached,
    )  # type: ignore[attr-defined]


def _annotate_due_state(ticket: Ticket, config: AppConfig) -> None:
    """Attach due-badge metadata used by templates."""

    base_color = ticket.display_color or config.colors.gradient_stage_color(0)

    if ticket.due_date:
        badge_label = f"Due {ticket.due_date.strftime('%b %d, %Y %H:%M')}"
        badge_state = "overdue" if getattr(ticket, "is_overdue", False) else "scheduled"
        badge_color = base_color
    elif getattr(ticket, "sla_countdown", None):
        badge_label = ticket.sla_countdown  # type: ignore[assignment]
        badge_state = "sla-breached" if getattr(ticket, "sla_is_breached", False) else "sla-active"
        badge_color = base_color
    else:
        badge_label = "No due date"
        badge_state = "none"
        badge_color = config.colors.gradient_stage_color(0)

    ticket.due_badge_label = badge_label  # type: ignore[attr-defined]
    ticket.due_badge_state = badge_state  # type: ignore[attr-defined]
    ticket.due_badge_color = badge_color  # type: ignore[attr-defined]


@dataclass(frozen=True)
class TooltipLink:
    """Normalized link metadata rendered in compact tooltips."""

    label: str
    href: str | None
    is_external: bool = False


@dataclass(frozen=True)
class TooltipAttachment:
    """Attachment metadata rendered in compact tooltips."""

    id: int
    display_name: str
    download_url: str
    meta: str | None = None


@dataclass
class TicketTooltipContext:
    """Context describing quick ticket details for tooltip rendering."""

    requester: str | None = None
    watchers: List[str] = field(default_factory=list)
    links: List[TooltipLink] = field(default_factory=list)
    attachments: List[TooltipAttachment] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not any((self.requester, self.watchers, self.links, self.attachments))


def _compose_compact_tooltip(ticket: Ticket) -> TicketTooltipContext | None:
    """Return structured tooltip content for compact ticket cards."""

    requester = (ticket.requester or "").strip() or None
    watchers = [watcher for watcher in ticket.watchers if watcher]
    links = _normalize_tooltip_links(ticket.links)
    attachments = _build_tooltip_attachments(ticket.attachments)

    context = TicketTooltipContext(
        requester=requester,
        watchers=watchers,
        links=links,
        attachments=attachments,
    )

    if context.is_empty():
        return None

    return context


def _normalize_tooltip_links(raw_links: str | None) -> List[TooltipLink]:
    if not raw_links:
        return []

    normalized = raw_links.replace("\r\n", "\n").replace("\r", "\n")
    segments = [segment.strip() for segment in normalized.split("\n") if segment.strip()]

    links: List[TooltipLink] = []
    for entry in segments:
        href = _resolve_link_href(entry)
        is_external = bool(href) and _is_external_href(href)
        links.append(TooltipLink(label=entry, href=href, is_external=is_external))
    return links


def _resolve_link_href(entry: str) -> str | None:
    parsed = urlparse(entry)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return entry
    if parsed.scheme in {"mailto", "tel"} and (parsed.path or parsed.netloc):
        return entry
    if entry.startswith(("/", "#")):
        return entry
    return None


def _is_external_href(href: str) -> bool:
    parsed = urlparse(href)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _build_tooltip_attachments(attachments: Iterable[Attachment]) -> List[TooltipAttachment]:
    tooltip_attachments: List[TooltipAttachment] = []
    for attachment in attachments:
        if attachment.id is None:
            continue
        meta = _format_attachment_meta(attachment)
        tooltip_attachments.append(
            TooltipAttachment(
                id=attachment.id,
                display_name=attachment.display_name,
                download_url=url_for(
                    "tickets.download_attachment", attachment_id=attachment.id
                ),
                meta=meta,
            )
        )
    return tooltip_attachments


def _format_attachment_meta(attachment: Attachment) -> str | None:
    details: List[str] = []

    size_label = _format_file_size(attachment.size)
    if size_label:
        details.append(size_label)

    if attachment.mimetype:
        details.append(attachment.mimetype)

    if attachment.uploaded_at:
        details.append(attachment.uploaded_at.strftime("%b %d, %Y %H:%M"))

    return " · ".join(details) if details else None


def _format_file_size(size: int | None) -> str | None:
    if size is None or size < 0:
        return None

    if size < 1024:
        return f"{size} B"

    units = ["KB", "MB", "GB", "TB", "PB"]
    value = float(size)
    for unit in units:
        value /= 1024.0
        if value < 1024.0:
            break
    formatted = f"{value:.1f}".rstrip("0").rstrip(".")
    return f"{formatted} {unit}"


def _boost_overdue_rgb(red: int, green: int, blue: int) -> tuple[int, int, int]:
    """Return an intensified RGB tuple for overdue overlays."""

    r_norm, g_norm, b_norm = (component / 255.0 for component in (red, green, blue))
    hue, lightness, saturation = colorsys.rgb_to_hls(r_norm, g_norm, b_norm)
    saturation = min(1.0, saturation * 1.25 + 0.05)
    lightness = max(0.0, min(1.0, lightness * 0.9 + 0.05))
    boosted_r, boosted_g, boosted_b = colorsys.hls_to_rgb(hue, lightness, saturation)
    return (
        int(round(boosted_r * 255)),
        int(round(boosted_g * 255)),
        int(round(boosted_b * 255)),
    )


def _is_ticket_overdue(
    ticket: Ticket,
    config: AppConfig,
    now: datetime | None = None,
) -> bool:
    """Return ``True`` when a ticket exceeds its SLA window."""

    current = now or datetime.utcnow()
    if ticket.due_date:
        return ticket.due_date <= current

    remaining = _compute_backlog_remaining_days(ticket, config, current)
    if remaining is None:
        return False
    return remaining < 0


def _is_compact_mode() -> bool:
    """Return ``True`` when the current request asks for compact mode."""

    value = request.args.get("compact")
    if value is None:
        return True

    normalized = value.strip().lower()
    if normalized in {"0", "false", "no", "off"}:
        return False
    if normalized in {"1", "true", "yes", "on"}:
        return True
    return True


def _compact_query_value(compact_mode: bool) -> str:
    return "1" if compact_mode else "0"


def _build_compact_toggle_url(endpoint: str, compact_mode: bool, **values: object) -> str:
    """Return a URL that toggles the compact flag while preserving filters."""

    query_args: Dict[str, List[str]] = {key: list(items) for key, items in request.args.lists()}
    toggled_value = _compact_query_value(not compact_mode)
    query_args["compact"] = [toggled_value]

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

    for upload in files:
        if not upload or not upload.filename:
            continue

        original_name = upload.filename
        safe_name = secure_filename(original_name) or "attachment"

        checksum = compute_stream_sha256(upload.stream)

        existing = (
            Attachment.query.filter_by(checksum=checksum)
            .order_by(Attachment.id.asc())
            .first()
        )
        if existing and not existing.stored_filename:
            existing = None

        stored_filename: str
        file_uuid: str
        file_size: int | None = None

        if existing:
            file_uuid = existing.file_uuid or generate_uuid7()
            if not existing.file_uuid:
                existing.file_uuid = file_uuid
            if not existing.checksum:
                existing.checksum = checksum
            stored_filename = existing.stored_filename
            target_path = upload_root / stored_filename

            if target_path.exists():
                file_size = existing.size
                if file_size is None:
                    try:
                        file_size = target_path.stat().st_size
                    except OSError:
                        file_size = None
            else:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                upload.save(target_path)
                try:
                    file_size = target_path.stat().st_size
                except OSError:
                    file_size = existing.size
        else:
            file_uuid = generate_uuid7()
            timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
            extension = Path(safe_name).suffix
            stored_name = f"{file_uuid}-{timestamp}{extension}"
            stored_filename = f"shared/{stored_name}"
            target_path = upload_root / stored_filename
            target_path.parent.mkdir(parents=True, exist_ok=True)
            upload.save(target_path)
            try:
                file_size = target_path.stat().st_size
            except OSError:
                file_size = None

        attachment = Attachment(
            ticket=ticket,
            update=update,
            original_filename=original_name,
            stored_filename=stored_filename,
            mimetype=upload.mimetype,
            size=file_size,
            checksum=checksum,
            file_uuid=file_uuid,
        )
        db.session.add(attachment)
        stored.append(attachment)

    return stored


@tickets_bp.route("/")
def list_tickets():
    config = _app_config()
    query = Ticket.query

    compact_mode = _is_compact_mode()
    title_color = config.colors.ticket_title_color()

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
        priority_case = case(
            *priority_mappings,
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
    now = datetime.utcnow()
    status_palette = _build_status_palette(config)
    for ticket in tickets:
        ticket.display_color = _compute_ticket_color(ticket, config, status_palette)  # type: ignore[attr-defined]
        ticket.status_color = (
            _resolve_status_color(ticket.status, status_palette)
            or ticket.display_color
        )  # type: ignore[attr-defined]
        _annotate_ticket_sla(ticket, config, now)
        _annotate_due_state(ticket, config)
        ticket.compact_tooltip = _compose_compact_tooltip(ticket)  # type: ignore[attr-defined]
        ticket.clipboard_summary = build_ticket_clipboard_summary(  # type: ignore[attr-defined]
            ticket,
            config,
        )

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
        ticket_title_color=title_color,
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
    title_color = config.colors.ticket_title_color()
    status_palette = _build_status_palette(config)
    ticket.display_color = _compute_ticket_color(ticket, config, status_palette)  # type: ignore[attr-defined]
    ticket.status_color = (
        _resolve_status_color(ticket.status, status_palette)
        or ticket.display_color
    )  # type: ignore[attr-defined]
    _annotate_ticket_sla(ticket, config)
    _annotate_due_state(ticket, config)
    ticket.clipboard_summary = build_ticket_clipboard_summary(  # type: ignore[attr-defined]
        ticket,
        config,
    )
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
        ticket_title_color=title_color,
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
                compact=_compact_query_value(compact_mode),
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
        redirect_endpoint = (
            "tickets.list_tickets"
            if config.auto_return_to_list
            else "tickets.ticket_detail"
        )
        redirect_kwargs = {"compact": _compact_query_value(compact_mode)}
        if redirect_endpoint == "tickets.ticket_detail":
            redirect_kwargs["ticket_id"] = ticket.id
        return redirect(url_for(redirect_endpoint, **redirect_kwargs))

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
    config = _app_config()
    compact_mode = _is_compact_mode()

    attachments = request.files.getlist("attachments")
    message = request.form.get("message", "").strip()
    submitted_by = (request.form.get("submitted_by") or "").strip()
    author = submitted_by or config.default_submitted_by
    new_status = request.form.get("status") or ticket.status
    hold_reason = request.form.get("on_hold_reason") or None
    raw_re_age = request.form.get("reage_ticket")
    re_age_requested = (raw_re_age or "").lower() in {"1", "true", "yes", "on"}
    auto_attachment_raw = request.form.get("auto_attachment")
    auto_attachment = (auto_attachment_raw or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    previous_status = ticket.status
    if new_status != ticket.status:
        ticket.status = new_status
        ticket.on_hold_reason = hold_reason if new_status == "On Hold" else None
        status_message = f"Status changed from {previous_status} to {new_status}"
        ticket.add_update(status_message, status_from=previous_status, status_to=new_status, is_system=True)

    if message:
        update = ticket.add_update(message, author=author)
    else:
        filenames = [
            upload.filename
            for upload in attachments
            if upload and upload.filename
        ]
        if filenames and auto_attachment:
            summary = ", ".join(filenames)
            attachment_body = f"Added attachment(s): {summary}"
            update = ticket.add_update(attachment_body, author=author)
        else:
            update = None

    db.session.flush()
    if not ticket.due_date and re_age_requested:
        ticket.age_reference_date = datetime.utcnow().date()

    _store_attachments(attachments, ticket, update=update)

    db.session.commit()
    flash("Update added", "success")
    redirect_endpoint = (
        "tickets.list_tickets"
        if config.auto_return_to_list
        else "tickets.ticket_detail"
    )
    redirect_kwargs = {"compact": _compact_query_value(compact_mode)}
    if redirect_endpoint == "tickets.ticket_detail":
        redirect_kwargs["ticket_id"] = ticket.id
    return redirect(url_for(redirect_endpoint, **redirect_kwargs))


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
                compact=_compact_query_value(compact_mode),
            )
        )

    return send_from_directory(
        directory=str(file_path.parent),
        path=file_path.name,
        as_attachment=True,
        download_name=attachment.original_filename,
        mimetype=attachment.mimetype or "application/octet-stream",
    )
