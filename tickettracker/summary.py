"""Utilities for composing clipboard-ready ticket summaries."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, List, Sequence

from flask import render_template

from .config import AppConfig
from .models import Ticket, TicketUpdate


CLIPBOARD_SUMMARY_SECTION_DESCRIPTIONS: Dict[str, str] = {
    "header": "Displays the ticket title as a heading.",
    "timestamps": "Shows the created and last updated timestamps.",
    "meta": "Lists status, priority, due date, and SLA countdown.",
    "people": "Summarises the requester and watchers.",
    "description": "Includes the ticket description body.",
    "links": "Copies the ticket's reference links field.",
    "notes": "Copies the internal notes field.",
    "tags": "Lists applied tags.",
    "updates": "Shows recent timeline updates with authors and changes.",
}


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

    available_sections = summary_config.available_sections()

    html = render_template(
        "partials/ticket_clipboard_summary.html",
        ticket=ticket,
        config=config,
        sections=resolved_html_sections,
        updates=updates,
        available_sections=available_sections,
    ).strip()

    text = render_template(
        "partials/ticket_clipboard_summary.txt",
        ticket=ticket,
        config=config,
        sections=resolved_text_sections,
        updates=updates,
        available_sections=available_sections,
    ).strip()

    return TicketClipboardSummary(html=html, text=text)
