"""Lightweight schema migration utilities for TicketTracker."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Tuple

from flask import current_app

from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from .extensions import db
from .utils.uploads import compute_file_sha256, generate_uuid7


def run_migrations() -> None:
    """Apply idempotent schema migrations required by the application."""

    engine = db.engine
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if "tickets" in table_names:
        _ensure_ticket_age_reference(engine, inspector)
    if "attachments" in table_names:
        _ensure_attachment_metadata(engine, inspector)


def _ensure_ticket_age_reference(engine, inspector) -> None:
    columns = {column["name"] for column in inspector.get_columns("tickets")}
    if "age_reference_date" in columns:
        return

    with engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE tickets ADD COLUMN age_reference_date DATE")
        )
        connection.execute(
            text(
                "UPDATE tickets "
                "SET age_reference_date = DATE(created_at) "
                "WHERE age_reference_date IS NULL"
            )
        )


def _ensure_attachment_metadata(engine, inspector) -> None:
    columns = {column["name"] for column in inspector.get_columns("attachments")}
    needs_checksum = "checksum" not in columns
    needs_uuid = "file_uuid" not in columns

    if needs_checksum or needs_uuid:
        with engine.begin() as connection:
            if needs_checksum:
                connection.execute(
                    text("ALTER TABLE attachments ADD COLUMN checksum VARCHAR(64)")
                )
            if needs_uuid:
                connection.execute(
                    text("ALTER TABLE attachments ADD COLUMN file_uuid VARCHAR(36)")
                )

    _backfill_attachment_metadata(engine)


def _backfill_attachment_metadata(engine) -> None:
    from .models import Attachment

    upload_root = Path(current_app.config["UPLOAD_FOLDER"])

    with Session(engine) as session:
        attachments = session.scalars(
            select(Attachment).order_by(Attachment.id.asc())
        )

        canonical: Dict[str, Tuple[str, str]] = {}
        dirty = False

        for attachment in attachments:
            stored_filename = attachment.stored_filename
            if not stored_filename:
                continue

            file_path = upload_root / stored_filename
            if not file_path.exists():
                continue

            checksum = attachment.checksum
            if not checksum:
                checksum = compute_file_sha256(file_path)
                attachment.checksum = checksum
                dirty = True

            canonical_entry = canonical.get(checksum)
            if canonical_entry is None:
                file_uuid = attachment.file_uuid or generate_uuid7()
                canonical_entry = (file_uuid, stored_filename)
                canonical[checksum] = canonical_entry

            file_uuid = canonical_entry[0]
            if attachment.file_uuid != file_uuid:
                attachment.file_uuid = file_uuid
                dirty = True

        if dirty:
            session.commit()

