"""Lightweight schema migration utilities for TicketTracker."""
from __future__ import annotations

from sqlalchemy import inspect, text

from .extensions import db


def run_migrations() -> None:
    """Apply idempotent schema migrations required by the application."""

    engine = db.engine
    inspector = inspect(engine)
    if "tickets" not in inspector.get_table_names():
        return

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

