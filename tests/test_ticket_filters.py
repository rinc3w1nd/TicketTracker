import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _write_config(target: Path, data: dict) -> Path:
    target.write_text(json.dumps(data, indent=2))
    return target


def _default_config() -> dict:
    from tickettracker.config import DEFAULT_CONFIG

    return json.loads(json.dumps(DEFAULT_CONFIG))


@pytest.fixture()
def app(tmp_path):
    from tickettracker.app import create_app

    config_data = _default_config()
    database_path = tmp_path / "app.db"
    uploads_path = tmp_path / "uploads"
    config_data["database"]["uri"] = f"sqlite:///{database_path}"
    config_data["uploads"]["directory"] = str(uploads_path)
    config_path = _write_config(tmp_path / "config.json", config_data)

    return create_app(config_path)


def test_active_filter_excludes_closed_and_cancelled(app):
    from tickettracker.extensions import db
    from tickettracker.models import Ticket

    with app.app_context():
        tickets = [
            Ticket(
                title="Open ticket",
                description="Keep me on the board",
                priority="Medium",
                status="Open",
            ),
            Ticket(
                title="Resolved ticket",
                description="Finished but awaiting review",
                priority="Medium",
                status="Resolved",
            ),
            Ticket(
                title="Closed ticket",
                description="Completed and archived",
                priority="Medium",
                status="Closed",
            ),
            Ticket(
                title="Cancelled ticket",
                description="No longer needed",
                priority="Medium",
                status="Cancelled",
            ),
        ]
        db.session.add_all(tickets)
        db.session.commit()

    client = app.test_client()
    response = client.get("/?status=Active")

    assert response.status_code == 200
    html = response.data.decode("utf-8")

    assert "Open ticket" in html
    assert "Resolved ticket" in html
    assert "Closed ticket" not in html
    assert "Cancelled ticket" not in html
    assert 'option value="Active" selected' in html

