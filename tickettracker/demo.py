"""Demo data loading utilities and demo-mode orchestration."""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from flask import Flask, current_app
from sqlalchemy import delete
from sqlalchemy.orm import Session, selectinload

from .extensions import db
from .migrations import run_migrations
from .models import Attachment, Tag, Ticket, TicketTag, TicketUpdate


class DemoModeError(RuntimeError):
    """Raised when demo-mode operations encounter an unrecoverable error."""


DATASET_FILENAME = "demo_tickets.json"
STATE_FILENAME = "state.json"
SNAPSHOT_DATABASE_FILENAME = "database.sqlite"
SNAPSHOT_UPLOADS_DIRNAME = "uploads"


@dataclass
class DemoModeState:
    """Persisted metadata tracking demo mode activity."""

    active: bool = False
    dataset_name: str = DATASET_FILENAME
    database_uri: str | None = None
    uploads_directory: str | None = None
    last_loaded_at: str | None = None
    had_database: bool = False
    had_uploads: bool = False

    @classmethod
    def load(cls, directory: Path) -> "DemoModeState":
        state_path = directory / STATE_FILENAME
        if not state_path.exists():
            return cls()
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise DemoModeError(f"Invalid demo mode state metadata: {exc}") from exc

        return cls(
            active=bool(payload.get("active", False)),
            dataset_name=str(payload.get("dataset_name", DATASET_FILENAME)),
            database_uri=payload.get("database_uri"),
            uploads_directory=payload.get("uploads_directory"),
            last_loaded_at=payload.get("last_loaded_at"),
            had_database=bool(payload.get("had_database", False)),
            had_uploads=bool(payload.get("had_uploads", False)),
        )

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        payload = {
            "active": self.active,
            "dataset_name": self.dataset_name,
            "database_uri": self.database_uri,
            "uploads_directory": self.uploads_directory,
            "last_loaded_at": self.last_loaded_at,
            "had_database": self.had_database,
            "had_uploads": self.had_uploads,
        }
        (directory / STATE_FILENAME).write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )


def _ensure_app(app: Flask | None = None) -> Flask:
    if app is not None:
        return app
    try:
        return current_app  # type: ignore[misc]
    except RuntimeError as exc:  # pragma: no cover - guard clause
        raise DemoModeError("An application context is required for demo operations.") from exc


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise DemoModeError(f"Invalid datetime value in demo dataset: {value!r}") from exc
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise DemoModeError(f"Invalid date value in demo dataset: {value!r}") from exc


def _normalize_watchers(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_entries = value.replace(";", ",").split(",")
    elif isinstance(value, Iterable):
        raw_entries = list(value)
    else:
        raw_entries = [value]

    watchers: List[str] = []
    seen: set[str] = set()
    for entry in raw_entries:
        text = str(entry or "").strip()
        if not text or text in seen:
            continue
        watchers.append(text)
        seen.add(text)
    return watchers


def _normalize_links(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, Iterable):
        flattened: List[str] = []
        for entry in value:
            text = str(entry or "").strip()
            if text:
                flattened.append(text)
        if not flattened:
            return None
        return "\n".join(flattened)
    return str(value)


def _write_attachment_file(
    uploads_directory: Path, stored_filename: str, content: Optional[str] = None
) -> Path:
    normalized_name = stored_filename.replace("\\", "/").lstrip("/")
    if not normalized_name:
        raise DemoModeError("Attachment stored filename cannot be empty")
    target_path = uploads_directory / normalized_name
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if content is not None:
        target_path.write_text(str(content), encoding="utf-8")
    elif not target_path.exists():
        target_path.write_text("Demo attachment placeholder", encoding="utf-8")
    return target_path


def load_demo_dataset(
    dataset_path: os.PathLike[str] | str,
    *,
    session: Optional[Session] = None,
    uploads_directory: os.PathLike[str] | str | None = None,
    use_transaction: bool = True,
) -> None:
    """Load demo tickets, tags, and related data from ``dataset_path``."""

    dataset = Path(dataset_path)
    if not dataset.exists():
        raise DemoModeError(f"Demo dataset not found: {dataset}")

    data = json.loads(dataset.read_text(encoding="utf-8"))

    raw_tags = data.get("tags", [])
    raw_tickets = data.get("tickets", [])

    session = session or db.session
    uploads_path = Path(uploads_directory) if uploads_directory else Path(current_app.config["UPLOAD_FOLDER"])
    uploads_path.mkdir(parents=True, exist_ok=True)

    def _populate() -> None:
        session.execute(delete(Attachment))
        session.execute(delete(TicketUpdate))
        session.execute(delete(TicketTag))
        session.execute(delete(Ticket))
        session.execute(delete(Tag))

        tag_map: Dict[str, Tag] = {}
        for tag_data in raw_tags:
            if not isinstance(tag_data, Mapping):
                continue
            name = str(tag_data.get("name", "")).strip()
            if not name:
                continue
            tag = Tag(name=name, color=tag_data.get("color"))
            session.add(tag)
            tag_map[name] = tag

        session.flush()

        for ticket_data in raw_tickets:
            if not isinstance(ticket_data, Mapping):
                continue
            title = str(ticket_data.get("title", "")).strip()
            description = str(ticket_data.get("description", "")).strip()
            if not title or not description:
                continue

            ticket = Ticket(
                title=title,
                description=description,
                requester=ticket_data.get("requester"),
                priority=str(ticket_data.get("priority", "Medium") or "Medium"),
                status=str(ticket_data.get("status", "Open") or "Open"),
                due_date=_parse_datetime(ticket_data.get("due_date")),
                notes=ticket_data.get("notes"),
                links=_normalize_links(ticket_data.get("links")),
                on_hold_reason=ticket_data.get("on_hold_reason"),
                created_at=_parse_datetime(ticket_data.get("created_at")) or datetime.utcnow(),
                updated_at=_parse_datetime(ticket_data.get("updated_at")) or datetime.utcnow(),
                age_reference_date=_parse_date(ticket_data.get("age_reference_date")),
            )

            watchers = _normalize_watchers(ticket_data.get("watchers"))
            if watchers:
                ticket.watchers = watchers

            session.add(ticket)
            session.flush()

            tag_names = [str(name) for name in ticket_data.get("tags", []) if str(name).strip()]
            resolved_tags = [tag_map[name.strip()] for name in tag_names if name.strip() in tag_map]
            if resolved_tags:
                ticket.tags = resolved_tags

            updates = ticket_data.get("updates", [])
            for update_data in updates:
                if not isinstance(update_data, Mapping):
                    continue
                update = TicketUpdate(
                    ticket=ticket,
                    body=str(update_data.get("body", "")).strip() or "Update",
                    author=update_data.get("author"),
                    created_at=_parse_datetime(update_data.get("created_at")) or datetime.utcnow(),
                    status_from=update_data.get("status_from"),
                    status_to=update_data.get("status_to"),
                    is_system=bool(update_data.get("is_system", False)),
                )
                session.add(update)
                session.flush()

                attachments = update_data.get("attachments", [])
                for attachment_data in attachments:
                    if not isinstance(attachment_data, Mapping):
                        continue
                    stored_filename = str(attachment_data.get("stored_filename", "")).strip()
                    if not stored_filename:
                        continue
                    content = attachment_data.get("content")
                    file_path = _write_attachment_file(uploads_path, stored_filename, content)
                    attachment = Attachment(
                        ticket=ticket,
                        update=update,
                        original_filename=attachment_data.get("original_filename")
                        or Path(stored_filename).name,
                        stored_filename=stored_filename,
                        mimetype=attachment_data.get("mimetype"),
                        size=int(attachment_data.get("size" or 0) or file_path.stat().st_size),
                        uploaded_at=_parse_datetime(attachment_data.get("uploaded_at"))
                        or update.created_at,
                    )
                    session.add(attachment)

            ticket_level_attachments = ticket_data.get("attachments", [])
            for attachment_data in ticket_level_attachments:
                if not isinstance(attachment_data, Mapping):
                    continue
                stored_filename = str(attachment_data.get("stored_filename", "")).strip()
                if not stored_filename:
                    continue
                content = attachment_data.get("content")
                file_path = _write_attachment_file(uploads_path, stored_filename, content)
                attachment = Attachment(
                    ticket=ticket,
                    original_filename=attachment_data.get("original_filename")
                    or Path(stored_filename).name,
                    stored_filename=stored_filename,
                    mimetype=attachment_data.get("mimetype"),
                    size=int(attachment_data.get("size" or 0) or file_path.stat().st_size),
                    uploaded_at=_parse_datetime(attachment_data.get("uploaded_at"))
                    or ticket.created_at,
                )
                session.add(attachment)

    if use_transaction:
        with session.begin():
            _populate()
    else:
        _populate()


class DemoModeManager:
    """Coordinate demo-mode lifecycle including dataset loading and restoration."""

    def __init__(self, app: Flask):
        self.app = app
        self.snapshot_root = Path(app.instance_path) / "demo_snapshot"
        self.state = DemoModeState.load(self.snapshot_root)
        self.dataset_path = (
            Path(app.root_path).resolve() / "demo_data" / self.state.dataset_name
        )
        self._last_loaded: datetime | None = (
            _parse_datetime(self.state.last_loaded_at) if self.state.last_loaded_at else None
        )

    @property
    def is_active(self) -> bool:
        return self.state.active

    @property
    def last_loaded_at(self) -> datetime | None:
        return self._last_loaded

    def _dataset(self) -> Path:
        dataset = self.dataset_path
        if not dataset.exists():
            raise DemoModeError(f"Demo dataset missing: {dataset}")
        return dataset

    def _uploads_path(self) -> Path:
        return Path(self.app.config["UPLOAD_FOLDER"]).resolve()

    def _database_path(self) -> Path:
        uri = str(self.app.config.get("SQLALCHEMY_DATABASE_URI", ""))
        if uri.endswith("/:memory:"):
            raise DemoModeError("Demo mode does not support in-memory SQLite databases.")
        if not uri.startswith("sqlite:///"):
            raise DemoModeError("Demo mode currently supports only SQLite database URIs.")
        raw_path = uri.replace("sqlite:///", "", 1)
        db_path = Path(raw_path)
        return db_path.resolve()

    def _dispose_engine(self) -> None:
        db.session.remove()
        try:
            engine = db.engine
        except RuntimeError:
            return
        engine.dispose()

    def _copy_database(self, source: Path, target: Path) -> None:
        if source.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    def _clear_uploads(self, path: Path) -> None:
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)

    def _ensure_snapshot(self) -> None:
        if self.state.active:
            # Snapshot already captured; nothing to do.
            return
        db_path = self._database_path()
        uploads_path = self._uploads_path()
        snapshot_db = self.snapshot_root / SNAPSHOT_DATABASE_FILENAME
        snapshot_uploads = self.snapshot_root / SNAPSHOT_UPLOADS_DIRNAME

        self.snapshot_root.mkdir(parents=True, exist_ok=True)
        if snapshot_db.exists():
            snapshot_db.unlink()
        if snapshot_uploads.exists():
            shutil.rmtree(snapshot_uploads)

        self._dispose_engine()
        self._copy_database(db_path, snapshot_db)
        if uploads_path.exists():
            shutil.copytree(uploads_path, snapshot_uploads)
        else:
            snapshot_uploads.mkdir(parents=True, exist_ok=True)

        self.state.had_database = db_path.exists()
        self.state.had_uploads = uploads_path.exists() and any(uploads_path.iterdir())
        self.state.database_uri = str(self.app.config.get("SQLALCHEMY_DATABASE_URI"))
        self.state.uploads_directory = str(uploads_path)

    def _restore_snapshot(self) -> None:
        db_path = self._database_path()
        uploads_path = self._uploads_path()
        snapshot_db = self.snapshot_root / SNAPSHOT_DATABASE_FILENAME
        snapshot_uploads = self.snapshot_root / SNAPSHOT_UPLOADS_DIRNAME

        self._dispose_engine()
        if db_path.exists():
            db_path.unlink()
        if self.state.had_database and snapshot_db.exists():
            self._copy_database(snapshot_db, db_path)
        else:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            db.create_all()
            run_migrations()

        self._clear_uploads(uploads_path)
        if self.state.had_uploads and snapshot_uploads.exists():
            shutil.copytree(snapshot_uploads, uploads_path, dirs_exist_ok=True)

    def enable(self) -> None:
        """Enable demo mode, snapshotting live data on first activation."""

        dataset_path = self._dataset()
        self._ensure_snapshot()

        db_path = self._database_path()
        uploads_path = self._uploads_path()

        try:
            self._dispose_engine()
            if db_path.exists():
                db_path.unlink()
            db_path.parent.mkdir(parents=True, exist_ok=True)
            db.create_all()
            run_migrations()

            self._clear_uploads(uploads_path)

            load_demo_dataset(
                dataset_path, session=db.session, uploads_directory=uploads_path
            )
        except DemoModeError:
            self._restore_snapshot()
            raise
        except Exception as exc:  # pragma: no cover - defensive branch
            self._restore_snapshot()
            raise DemoModeError(f"Unexpected error enabling demo mode: {exc}") from exc

        self.state.active = True
        self.state.dataset_name = dataset_path.name
        timestamp = datetime.utcnow().replace(tzinfo=timezone.utc)
        self.state.last_loaded_at = timestamp.isoformat()
        self._last_loaded = timestamp
        self.dataset_path = dataset_path
        self.state.save(self.snapshot_root)
        self.app.config["DEMO_MODE"] = True

    def disable(self) -> None:
        """Disable demo mode and restore the original snapshot."""

        if not self.state.active:
            return

        self._restore_snapshot()

        self.state.active = False
        self.state.last_loaded_at = None
        self._last_loaded = None
        self.state.save(self.snapshot_root)
        self.app.config["DEMO_MODE"] = False

        # Clean up snapshot artifacts so a future enable captures a fresh snapshot.
        snapshot_db = self.snapshot_root / SNAPSHOT_DATABASE_FILENAME
        snapshot_uploads = self.snapshot_root / SNAPSHOT_UPLOADS_DIRNAME
        if snapshot_db.exists():
            snapshot_db.unlink()
        if snapshot_uploads.exists():
            shutil.rmtree(snapshot_uploads)

    def persist_dataset(self) -> Path:
        """Persist the in-memory demo dataset back to the active dataset file."""

        if not self.state.active:
            raise DemoModeError(
                "Demo mode is not currently active; enable it before persisting."
            )

        dataset_path = self._dataset()
        uploads_path = self._uploads_path()

        try:
            existing_payload = json.loads(dataset_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            existing_payload = {}
        except json.JSONDecodeError:
            existing_payload = {}

        timestamp = datetime.utcnow().replace(tzinfo=timezone.utc)
        metadata = dict(existing_payload.get("metadata", {}))
        metadata["generated_at"] = timestamp.isoformat()

        def _format_datetime(value: datetime | None) -> str | None:
            if value is None:
                return None
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            else:
                value = value.astimezone(timezone.utc)
            return value.isoformat()

        def _format_date(value: date | None) -> str | None:
            return value.isoformat() if value else None

        uploads_root = uploads_path

        def _relative_stored_name(stored: str) -> str:
            candidate = Path(stored)
            try:
                return candidate.relative_to(uploads_root).as_posix()
            except ValueError:
                return candidate.as_posix()

        def _serialize_attachment(attachment: Attachment) -> Dict[str, Any]:
            data: Dict[str, Any] = {
                "original_filename": attachment.original_filename,
                "stored_filename": _relative_stored_name(attachment.stored_filename),
            }
            if attachment.mimetype:
                data["mimetype"] = attachment.mimetype
            if attachment.size is not None:
                data["size"] = attachment.size
            if attachment.checksum:
                data["checksum"] = attachment.checksum
            if attachment.file_uuid:
                data["file_uuid"] = attachment.file_uuid
            uploaded_at = _format_datetime(attachment.uploaded_at)
            if uploaded_at:
                data["uploaded_at"] = uploaded_at
            return data

        ticket_query = (
            Ticket.query.options(
                selectinload(Ticket.tags),
                selectinload(Ticket.updates).selectinload(TicketUpdate.attachments),
                selectinload(Ticket.attachments),
            )
            .order_by(Ticket.id)
            .all()
        )

        tickets_payload: List[Dict[str, Any]] = []
        for ticket in ticket_query:
            ticket_data: Dict[str, Any] = {
                "title": ticket.title,
                "description": ticket.description,
                "priority": ticket.priority,
                "status": ticket.status,
            }

            optional_fields = {
                "requester": ticket.requester,
                "notes": ticket.notes,
                "links": (
                    [part.strip() for part in (ticket.links or "").splitlines() if part.strip()]
                    if ticket.links
                    else None
                ),
                "on_hold_reason": ticket.on_hold_reason,
                "due_date": _format_datetime(ticket.due_date),
                "created_at": _format_datetime(ticket.created_at),
                "updated_at": _format_datetime(ticket.updated_at),
                "age_reference_date": _format_date(ticket.age_reference_date),
            }

            for key, value in optional_fields.items():
                if value:
                    ticket_data[key] = value

            watchers = ticket.watchers
            if watchers:
                ticket_data["watchers"] = watchers

            tag_names = sorted({tag.name for tag in ticket.tags})
            if tag_names:
                ticket_data["tags"] = tag_names

            updates_payload: List[Dict[str, Any]] = []
            for update in ticket.updates:
                update_data: Dict[str, Any] = {
                    "body": update.body,
                }
                update_optional = {
                    "author": update.author,
                    "created_at": _format_datetime(update.created_at),
                    "status_from": update.status_from,
                    "status_to": update.status_to,
                }
                for key, value in update_optional.items():
                    if value:
                        update_data[key] = value
                if update.is_system:
                    update_data["is_system"] = True

                update_attachments = [
                    _serialize_attachment(att)
                    for att in sorted(update.attachments, key=lambda item: item.id or 0)
                ]
                if update_attachments:
                    update_data["attachments"] = update_attachments
                updates_payload.append(update_data)

            if updates_payload:
                ticket_data["updates"] = updates_payload

            ticket_level_attachments = [
                _serialize_attachment(attachment)
                for attachment in sorted(ticket.attachments, key=lambda item: item.id or 0)
                if attachment.update_id is None
            ]
            if ticket_level_attachments:
                ticket_data["attachments"] = ticket_level_attachments

            tickets_payload.append(ticket_data)

        tags_payload = []
        for tag in Tag.query.order_by(Tag.name).all():
            entry: Dict[str, Any] = {"name": tag.name}
            if tag.color:
                entry["color"] = tag.color
            tags_payload.append(entry)

        payload = {
            "metadata": metadata,
            "tags": tags_payload,
            "tickets": tickets_payload,
        }

        dataset_path.parent.mkdir(parents=True, exist_ok=True)
        dataset_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        self._last_loaded = timestamp
        self.state.last_loaded_at = timestamp.isoformat()
        self.state.save(self.snapshot_root)
        return dataset_path

    def refresh(self) -> None:
        """Reload the demo dataset, discarding any interim demo changes."""

        if not self.state.active:
            raise DemoModeError("Demo mode is not currently active; enable it first.")
        self.enable()

    def status(self) -> Dict[str, Any]:
        """Return runtime status metadata for presentation layers."""

        try:
            dataset = str(self._dataset())
        except DemoModeError:
            dataset = str(self.dataset_path)
        return {
            "active": self.state.active,
            "dataset": dataset,
            "snapshot_root": str(self.snapshot_root),
            "last_loaded_at": self._last_loaded,
        }


def get_demo_manager(app: Flask | None = None) -> DemoModeManager:
    """Return (and cache) the :class:`DemoModeManager` for ``app``."""

    flask_app = _ensure_app(app)
    key = "tickettracker_demo_manager"
    manager: DemoModeManager | None = flask_app.extensions.get(key)  # type: ignore[assignment]
    if manager is None:
        manager = DemoModeManager(flask_app)
        flask_app.extensions[key] = manager
    return manager

