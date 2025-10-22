"""Utilities for composing clipboard-ready ticket summaries."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List, Sequence

from flask import render_template, url_for

from .config import AppConfig
from .models import Ticket, TicketUpdate


@dataclass
class TicketClipboardSummary:
    """Rendered clipboard payload for a ticket."""

    html: str
    text: str


def _normalize_sections(values: Iterable[str]) -> List[str]:
    sections: List[str] = []
    for value in values:
        text = str(value or "").strip().lower()
        if not text or text in sections:
            continue
        sections.append(text)
    return sections


def _recent_updates(ticket: Ticket, limit: int) -> List[TicketUpdate]:
    if limit <= 0:
        return []

    updates = sorted(
        ticket.updates,
        key=lambda update: update.created_at or datetime.min,
        reverse=True,
    )
    return updates[:limit]


def build_ticket_clipboard_summary(
    ticket: Ticket,
    config: AppConfig,
    *,
    html_sections: Sequence[str] | None = None,
    text_sections: Sequence[str] | None = None,
) -> TicketClipboardSummary:
    """Render HTML and plain-text clipboard payloads for ``ticket``."""

    summary_config = config.clipboard_summary

    resolved_html_sections = _normalize_sections(
        html_sections or summary_config.sections_for_html()
    )
    resolved_text_sections = _normalize_sections(
        text_sections or summary_config.sections_for_text()
    )

    updates_limit = summary_config.max_updates()
    updates = _recent_updates(ticket, updates_limit)

    try:
        ticket_url = url_for("tickets.ticket_detail", ticket_id=ticket.id, _external=True)
    except RuntimeError:
        ticket_url = None

    html = render_template(
        "partials/ticket_clipboard_summary.html",
        ticket=ticket,
        config=config,
        sections=resolved_html_sections,
        updates=updates,
        ticket_url=ticket_url,
    ).strip()

    text = render_template(
        "partials/ticket_clipboard_summary.txt",
        ticket=ticket,
        config=config,
        sections=resolved_text_sections,
        updates=updates,
        ticket_url=ticket_url,
    ).strip()

    return TicketClipboardSummary(html=html, text=text)
