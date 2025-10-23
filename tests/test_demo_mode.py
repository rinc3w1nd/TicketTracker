import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from flask import current_app

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tickettracker.app import create_app
from tickettracker.config import DEFAULT_CONFIG
from tickettracker.demo import DemoModeError, get_demo_manager
from tickettracker.extensions import db
from tickettracker.models import Ticket


def _write_config(target: Path, data: dict) -> Path:
    target.write_text(json.dumps(data, indent=2))
    return target


def _default_config() -> dict:
    return json.loads(json.dumps(DEFAULT_CONFIG))


@pytest.fixture()
def app_with_storage(tmp_path):
    config_data = _default_config()
    database_path = tmp_path / "app.db"
    uploads_path = tmp_path / "uploads"
    config_data["database"]["uri"] = f"sqlite:///{database_path}"
    config_data["uploads"]["directory"] = str(uploads_path)
    config_path = _write_config(tmp_path / "config.json", config_data)
    app = create_app(config_path)
    return app, config_path, uploads_path


def test_demo_mode_enable_and_disable_restores_snapshot(app_with_storage):
    app, config_path, uploads_path = app_with_storage

    with app.app_context():
        uploads_path.mkdir(parents=True, exist_ok=True)
        (uploads_path / "original.txt").write_text("original data", encoding="utf-8")

        ticket = Ticket(
            title="Original Ticket",
            description="This ticket should be restored after demo mode ends.",
            priority="Medium",
            status="Open",
        )
        db.session.add(ticket)
        db.session.commit()

        manager = get_demo_manager(current_app)
        assert manager.is_active is False

        manager.enable()
        assert manager.is_active is True
        assert current_app.config["DEMO_MODE"] is True

        demo_tickets = Ticket.query.order_by(Ticket.id).all()
        assert len(demo_tickets) == 5
        assert any(
            "Gateway outage" in ticket.title for ticket in demo_tickets
        ), "Expected seeded dataset to load."
        assert (uploads_path / "demo" / "failover-plan.txt").exists()

        manager.disable()
        assert manager.is_active is False
        assert current_app.config["DEMO_MODE"] is False

        restored_tickets = Ticket.query.order_by(Ticket.id).all()
        assert len(restored_tickets) == 1
        assert restored_tickets[0].title == "Original Ticket"
        assert (uploads_path / "original.txt").read_text(encoding="utf-8") == "original data"
        assert not (uploads_path / "demo").exists()

        persisted = json.loads(config_path.read_text())
        assert persisted["demo_mode"] is False


def test_demo_mode_refresh_resets_changes(app_with_storage):
    app, _, uploads_path = app_with_storage

    with app.app_context():
        manager = get_demo_manager(current_app)
        manager.enable()

        ticket = Ticket.query.filter(Ticket.title.contains("Gateway outage")).first()
        assert ticket is not None
        ticket.title = "Modified title"
        db.session.commit()

        manager.refresh()

        refreshed = Ticket.query.filter(Ticket.title.contains("Gateway outage")).first()
        assert refreshed is not None
        assert refreshed.title == "Gateway outage affecting checkout"
        assert (uploads_path / "demo" / "failover-plan.txt").exists()


def test_settings_toggle_demo_mode_route(app_with_storage):
    app, config_path, uploads_path = app_with_storage

    client = app.test_client()

    response = client.post("/settings/demo-mode", data={"action": "enable"}, follow_redirects=True)
    assert response.status_code == 200

    with app.app_context():
        manager = get_demo_manager(current_app)
        assert manager.is_active is True
        assert current_app.config["APP_CONFIG"].demo_mode is True
        assert Ticket.query.count() == 5
        assert (uploads_path / "demo" / "duplicate-report.csv").exists()

    response = client.post("/settings/demo-mode", data={"action": "refresh"}, follow_redirects=True)
    assert response.status_code == 200

    response = client.post("/settings/demo-mode", data={"action": "disable"}, follow_redirects=True)
    assert response.status_code == 200

    with app.app_context():
        manager = get_demo_manager(current_app)
        assert manager.is_active is False
        assert current_app.config["APP_CONFIG"].demo_mode is False
        assert Ticket.query.count() == 0
        assert not (uploads_path / "demo").exists()

    persisted = json.loads(config_path.read_text())
    assert persisted["demo_mode"] is False


def test_persist_action_requires_active_demo_mode(app_with_storage):
    app, _, _ = app_with_storage

    client = app.test_client()

    with app.app_context():
        manager = get_demo_manager(current_app)
        dataset_path = manager.dataset_path
        original_content = dataset_path.read_text(encoding="utf-8")

    response = client.post(
        "/settings/demo-mode", data={"action": "persist"}, follow_redirects=True
    )
    assert response.status_code == 200
    html = response.data.decode("utf-8")
    assert "Enable demo mode" in html

    with app.app_context():
        manager = get_demo_manager(current_app)
        assert manager.is_active is False
        assert dataset_path.read_text(encoding="utf-8") == original_content


def test_persist_action_updates_dataset_file(app_with_storage):
    app, _, _ = app_with_storage

    client = app.test_client()

    enable_response = client.post(
        "/settings/demo-mode", data={"action": "enable"}, follow_redirects=True
    )
    assert enable_response.status_code == 200

    with app.app_context():
        manager = get_demo_manager(current_app)
        dataset_path = manager.dataset_path
        original_payload = dataset_path.read_text(encoding="utf-8")
        original_metadata = json.loads(original_payload)["metadata"]["generated_at"]

        new_title = "Persisted dataset ticket"
        ticket = Ticket(
            title=new_title,
            description="Ticket added before persisting dataset.",
            priority="Low",
            status="Open",
        )
        db.session.add(ticket)
        db.session.commit()

    try:
        persist_response = client.post(
            "/settings/demo-mode", data={"action": "persist"}, follow_redirects=True
        )
        assert persist_response.status_code == 200
        body = persist_response.data.decode("utf-8")
        assert "Demo dataset saved" in body

        with app.app_context():
            manager = get_demo_manager(current_app)
            assert manager.is_active is True
            assert current_app.config["APP_CONFIG"].demo_mode is True

            updated_payload = json.loads(dataset_path.read_text(encoding="utf-8"))
            titles = [item["title"] for item in updated_payload["tickets"]]
            assert new_title in titles
            assert updated_payload["metadata"]["generated_at"] != original_metadata
    finally:
        with app.app_context():
            dataset_path.write_text(original_payload, encoding="utf-8")
            try:
                get_demo_manager(current_app).disable()
            except DemoModeError:
                pass

def test_priority_sorting_uses_configured_order(app_with_storage):
    app, _, _ = app_with_storage

    client = app.test_client()

    with app.app_context():
        config = current_app.config["APP_CONFIG"]
        expected_order = list(config.priorities)
        now = datetime.utcnow()

        for index, priority in enumerate(reversed(expected_order)):
            offset = timedelta(minutes=index)
            ticket = Ticket(
                title=f"{priority} priority ticket",
                description="Ticket created for priority sort regression test.",
                priority=priority,
                status="Open",
                created_at=now - offset,
                updated_at=now - offset,
            )
            db.session.add(ticket)

        unmatched_priority = "Unplanned"
        db.session.add(
            Ticket(
                title="Unplanned priority ticket",
                description="Ticket with an unmatched priority should be last.",
                priority=unmatched_priority,
                status="Open",
                created_at=now + timedelta(minutes=1),
                updated_at=now + timedelta(minutes=1),
            )
        )

        db.session.commit()

    response = client.get("/?sort=priority")
    assert response.status_code == 200

    html = response.data.decode("utf-8")
    priority_badges = re.findall(
        r"class=\"priority-badge\"[^>]*data-priority=\"([^\"]+)\"",
        html,
    )

    assert len(priority_badges) == len(expected_order) + 1
    assert priority_badges[: len(expected_order)] == expected_order
    assert priority_badges[-1] == unmatched_priority
