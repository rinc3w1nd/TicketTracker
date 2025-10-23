import io
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from flask import current_app, url_for

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tickettracker.app import create_app
from tickettracker.config import DEFAULT_CONFIG
from tickettracker.extensions import db
from tickettracker.models import Attachment, Ticket, TicketUpdate


def _write_config(target: Path, data: dict) -> Path:
    target.write_text(json.dumps(data, indent=2))
    return target


def _default_config() -> dict:
    return json.loads(json.dumps(DEFAULT_CONFIG))


def _create_app_with_ticket(tmp_path: Path, *, auto_return: bool) -> tuple:
    config_data = _default_config()
    database_path = tmp_path / "app.db"
    uploads_path = tmp_path / "uploads"
    config_data["database"]["uri"] = f"sqlite:///{database_path}"
    config_data["uploads"]["directory"] = str(uploads_path)
    config_data.setdefault("behavior", {})["auto_return_to_list"] = auto_return
    config_path = _write_config(tmp_path / "config.json", config_data)

    app = create_app(config_path)

    with app.app_context():
        ticket = Ticket(
            title="Ticket for attachment updates",
            description="Ensure attachment-only posts create timeline entries.",
            priority="Medium",
            status="Open",
        )
        db.session.add(ticket)
        db.session.commit()
        ticket_id = ticket.id

    return app, uploads_path, ticket_id


@pytest.fixture()
def app_with_ticket(tmp_path):
    return _create_app_with_ticket(tmp_path, auto_return=False)


@pytest.fixture()
def app_with_auto_return_ticket(tmp_path):
    return _create_app_with_ticket(tmp_path, auto_return=True)


def test_auto_attachment_posts_create_update(app_with_ticket):
    app, uploads_path, ticket_id = app_with_ticket
    client = app.test_client()

    data = {
        "message": "",
        "submitted_by": "",
        "status": "Open",
        "auto_attachment": "1",
        "attachments": [
            (io.BytesIO(b"first"), "first.txt"),
            (io.BytesIO(b"second"), "second.txt"),
        ],
    }

    response = client.post(
        f"/tickets/{ticket_id}/updates",
        data=data,
        content_type="multipart/form-data",
    )

    assert response.status_code == 302
    redirect_url = urlparse(response.headers["Location"])

    with app.test_request_context():
        expected_path = url_for("tickets.ticket_detail", ticket_id=ticket_id)

    assert redirect_url.path == expected_path
    assert parse_qs(redirect_url.query).get("compact") == ["1"]

    with app.app_context():
        updates = TicketUpdate.query.filter_by(ticket_id=ticket_id).all()
        assert len(updates) == 1
        update = updates[0]

        expected_body = "Added attachment(s): first.txt, second.txt"
        assert update.body == expected_body

        default_author = current_app.config["APP_CONFIG"].default_submitted_by
        assert update.author == default_author

        attachments = Attachment.query.filter_by(ticket_id=ticket_id).all()
        assert len(attachments) == 2
        assert {attachment.original_filename for attachment in attachments} == {
            "first.txt",
            "second.txt",
        }
        assert all(attachment.update_id == update.id for attachment in attachments)

        for attachment in attachments:
            stored_path = uploads_path / attachment.stored_filename
            assert stored_path.exists(), f"Expected {stored_path} to exist"


def test_edit_ticket_redirects_to_detail_by_default(app_with_ticket):
    app, _, ticket_id = app_with_ticket
    client = app.test_client()

    response = client.post(
        f"/tickets/{ticket_id}/edit?compact=0",
        data={
            "title": "Updated title",
            "description": "Updated description",
            "priority": "Medium",
            "status": "Open",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    redirect_url = urlparse(response.headers["Location"])

    with app.test_request_context():
        expected_path = url_for("tickets.ticket_detail", ticket_id=ticket_id)

    assert redirect_url.path == expected_path
    assert parse_qs(redirect_url.query).get("compact") == ["0"]


def test_edit_ticket_redirects_to_list_when_auto_return_enabled(
    app_with_auto_return_ticket,
):
    app, _, ticket_id = app_with_auto_return_ticket
    client = app.test_client()

    response = client.post(
        f"/tickets/{ticket_id}/edit?compact=0",
        data={
            "title": "Updated title",
            "description": "Updated description",
            "priority": "Medium",
            "status": "Open",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    redirect_url = urlparse(response.headers["Location"])

    with app.test_request_context():
        expected_path = url_for("tickets.list_tickets")

    assert redirect_url.path == expected_path
    assert parse_qs(redirect_url.query).get("compact") == ["0"]


def test_add_update_redirects_to_list_when_auto_return_enabled(
    app_with_auto_return_ticket,
):
    app, _, ticket_id = app_with_auto_return_ticket
    client = app.test_client()

    response = client.post(
        f"/tickets/{ticket_id}/updates?compact=0",
        data={
            "message": "Follow-up note",
            "status": "Open",
        },
    )

    assert response.status_code == 302
    redirect_url = urlparse(response.headers["Location"])

    with app.test_request_context():
        expected_path = url_for("tickets.list_tickets")

    assert redirect_url.path == expected_path
    assert parse_qs(redirect_url.query).get("compact") == ["0"]
