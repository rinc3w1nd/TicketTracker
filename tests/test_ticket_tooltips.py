import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
  sys.path.insert(0, str(ROOT))

from tickettracker.app import create_app
from tickettracker.config import DEFAULT_CONFIG
from tickettracker.extensions import db
from tickettracker.models import Attachment, Ticket


def _write_config(target: Path, data: dict) -> Path:
  target.write_text(json.dumps(data, indent=2))
  return target


def _default_config() -> dict:
  return json.loads(json.dumps(DEFAULT_CONFIG))


@pytest.fixture()
def tooltip_app(tmp_path):
  config = _default_config()
  database_path = tmp_path / "app.db"
  uploads_path = tmp_path / "uploads"
  config["database"]["uri"] = f"sqlite:///{database_path}"
  config["uploads"]["directory"] = str(uploads_path)
  config_path = _write_config(tmp_path / "config.json", config)

  app = create_app(config_path)

  with app.app_context():
    ticket = Ticket(
      title="Tooltip Ticket",
      description="Ensure compact tooltips render rich metadata.",
      priority="High",
      status="Open",
    )
    db.session.add(ticket)
    db.session.commit()
    ticket_id = ticket.id

  return app, ticket_id


def test_compact_tooltip_renders_interactive_card(tooltip_app):
  app, ticket_id = tooltip_app

  with app.app_context():
    ticket = Ticket.query.get(ticket_id)
    ticket.requester = "Ava Analyst"
    ticket.watchers = ["Bea Builder", "Cal Collaborator"]
    ticket.links = "https://example.com/docs\nInternal Checklist"
    attachment = Attachment(
      ticket=ticket,
      original_filename="report.pdf",
      stored_filename="report.pdf",
      mimetype="application/pdf",
      size=2048,
    )
    db.session.add(attachment)
    db.session.commit()
    attachment_id = attachment.id

  client = app.test_client()
  response = client.get("/")

  assert response.status_code == 200
  html = response.get_data(as_text=True)

  assert f'data-tooltip-id="ticket-tooltip-{ticket_id}"' in html
  assert f'id="ticket-tooltip-{ticket_id}"' in html
  assert 'class="ticket-tooltip"' in html
  assert "Quick ticket info" in html
  assert "Ava Analyst" in html
  assert "Bea Builder, Cal Collaborator" in html
  assert "https://example.com/docs" in html
  assert "Internal Checklist" in html
  assert f"/attachments/{attachment_id}" in html
  assert "application/pdf" in html
  assert "2 KB" in html
  assert 'data-ticket-tooltip-trigger' in html
