import io
import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from flask import current_app

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


@pytest.fixture()
def make_app_with_ticket(tmp_path):
    def _create(*, auto_return_to_list: bool = False):
        config_data = _default_config()
        database_path = tmp_path / "app.db"
        uploads_path = tmp_path / "uploads"
        config_data["database"]["uri"] = f"sqlite:///{database_path}"
        config_data["uploads"]["directory"] = str(uploads_path)
        config_data.setdefault("behavior", {})["auto_return_to_list"] = (
            auto_return_to_list
        )
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

    return _create


def test_auto_attachment_posts_create_update(make_app_with_ticket):
    app, uploads_path, ticket_id = make_app_with_ticket()
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


def test_attachment_deduplication_reuses_existing_file(make_app_with_ticket):
    app, uploads_path, ticket_id = make_app_with_ticket()
    client = app.test_client()

    initial = {
        "message": "",
        "submitted_by": "Tester",
        "status": "Open",
        "attachments": [(io.BytesIO(b"duplicate payload"), "first.txt")],
    }

    follow_up = {
        "message": "",
        "submitted_by": "Tester",
        "status": "Open",
        "attachments": [(io.BytesIO(b"duplicate payload"), "second.txt")],
    }

    response = client.post(
        f"/tickets/{ticket_id}/updates",
        data=initial,
        content_type="multipart/form-data",
    )
    assert response.status_code == 302

    response = client.post(
        f"/tickets/{ticket_id}/updates",
        data=follow_up,
        content_type="multipart/form-data",
    )
    assert response.status_code == 302

    with app.app_context():
        attachments = (
            Attachment.query.filter_by(ticket_id=ticket_id)
            .order_by(Attachment.id.asc())
            .all()
        )
        assert len(attachments) == 2
        first, second = attachments

        assert first.checksum == second.checksum
        assert first.stored_filename == second.stored_filename
        assert first.file_uuid == second.file_uuid
        assert first.stored_filename.startswith("shared/")

        shared_path = uploads_path / first.stored_filename
        assert shared_path.exists()
        shared_directory = uploads_path / "shared"
        shared_files = list(shared_directory.glob("*")) if shared_directory.exists() else []
        assert len(shared_files) == 1


def test_new_attachment_generates_uuid_filename(make_app_with_ticket):
    app, uploads_path, ticket_id = make_app_with_ticket()
    client = app.test_client()

    data = {
        "message": "",
        "submitted_by": "",
        "status": "Open",
        "attachments": [(io.BytesIO(b"unique content"), "note.txt")],
    }

    response = client.post(
        f"/tickets/{ticket_id}/updates",
        data=data,
        content_type="multipart/form-data",
    )
    assert response.status_code == 302

    with app.app_context():
        attachment = Attachment.query.filter_by(ticket_id=ticket_id).one()
        assert attachment.checksum is not None
        assert len(attachment.checksum) == 64
        assert attachment.file_uuid

        stored_filename = attachment.stored_filename
        assert stored_filename.startswith("shared/")
        uuid_part = stored_filename.split("/", 1)[1]
        pattern = re.compile(
            r"^([0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})-\d{20}\.txt$"
        )
        match = pattern.match(uuid_part)
        assert match, f"Unexpected stored filename format: {stored_filename}"
        assert match.group(1) == attachment.file_uuid

        stored_path = uploads_path / stored_filename
        assert stored_path.exists()


def test_add_update_redirects_to_detail_by_default(make_app_with_ticket):
    app, _, ticket_id = make_app_with_ticket()
    client = app.test_client()

    response = client.post(
        f"/tickets/{ticket_id}/updates",
        data={"message": "Progress", "submitted_by": "", "status": "Open"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    location = urlparse(response.headers["Location"])
    assert location.path == f"/tickets/{ticket_id}"
    assert parse_qs(location.query).get("compact") == ["1"]


def test_add_update_redirects_to_list_when_enabled(make_app_with_ticket):
    app, _, ticket_id = make_app_with_ticket(auto_return_to_list=True)
    client = app.test_client()

    response = client.post(
        f"/tickets/{ticket_id}/updates",
        data={"message": "Progress", "submitted_by": "", "status": "Open"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    location = urlparse(response.headers["Location"])
    assert location.path == "/"
    assert parse_qs(location.query).get("compact") == ["1"]


def test_edit_ticket_redirects_to_detail_by_default(make_app_with_ticket):
    app, _, ticket_id = make_app_with_ticket()
    client = app.test_client()

    response = client.post(
        f"/tickets/{ticket_id}/edit",
        data={"title": "Updated title"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    location = urlparse(response.headers["Location"])
    assert location.path == f"/tickets/{ticket_id}"
    assert parse_qs(location.query).get("compact") == ["1"]


def test_edit_ticket_redirects_to_list_when_enabled(make_app_with_ticket):
    app, _, ticket_id = make_app_with_ticket(auto_return_to_list=True)
    client = app.test_client()

    response = client.post(
        f"/tickets/{ticket_id}/edit",
        data={"title": "Updated title"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    location = urlparse(response.headers["Location"])
    assert location.path == "/"
    assert parse_qs(location.query).get("compact") == ["1"]
