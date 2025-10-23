"""Tests for the configuration settings workflow."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flask import current_app
from werkzeug.datastructures import MultiDict

from tickettracker.app import create_app
from tickettracker.config import DEFAULT_CONFIG, load_config


def _write_config(target: Path, data: dict) -> Path:
    target.write_text(json.dumps(data, indent=2))
    return target


def _default_config() -> dict:
    return json.loads(json.dumps(DEFAULT_CONFIG))


def test_load_config_records_source_path(tmp_path):
    config_data = _default_config()
    config_data["database"]["uri"] = "sqlite:///:memory:"
    config_path = _write_config(tmp_path / "config.json", config_data)

    config = load_config(config_path)

    assert config.source_path == config_path.resolve()
    payload = config.to_json_dict()
    assert payload["demo_mode"] is False
    assert payload["database"]["uri"].endswith("/:memory:")
    assert payload["clipboard_summary"]["html_sections"][1] == "timestamps"
    assert payload["clipboard_summary"]["text_sections"][1] == "timestamps"
    assert payload["clipboard_summary"]["debug_status"] is False
    assert payload["clipboard_summary"]["inline_styles"] is False


def test_settings_update_persists_between_app_starts(tmp_path):
    config_data = _default_config()
    database_path = tmp_path / "app.db"
    uploads_dir = "uploads"
    config_data["database"]["uri"] = f"sqlite:///{database_path}"
    config_data["uploads"]["directory"] = uploads_dir
    config_path = _write_config(tmp_path / "config.json", config_data)

    app = create_app(config_path)

    client = app.test_client()
    response = client.post(
        "/settings",
        data=MultiDict(
            [
                ("default_submitted_by", "Operations Team"),
                ("priorities", "Low\nMedium\nHigh\nUrgent"),
                ("hold_reasons", "Awaiting info\nReview pending"),
                ("workflow", "New\nActive\nDone"),
                ("html_sections", "header"),
                ("html_sections", "timestamps"),
                ("html_sections", "meta"),
                ("text_sections", "header"),
                ("text_sections", "timestamps"),
                ("text_sections", "meta"),
                ("text_sections", "updates"),
                ("updates_limit", "3"),
                ("demo_mode", "on"),
            ]
        ),
        follow_redirects=True,
    )

    assert response.status_code == 200

    persisted = json.loads(config_path.read_text())
    assert persisted["default_submitted_by"] == "Operations Team"
    assert persisted["priorities"] == ["Low", "Medium", "High", "Urgent"]
    assert persisted["hold_reasons"] == ["Awaiting info", "Review pending"]
    assert persisted["workflow"] == ["New", "Active", "Done"]
    assert persisted["clipboard_summary"]["html_sections"] == [
        "header",
        "timestamps",
        "meta",
    ]
    assert persisted["clipboard_summary"]["text_sections"] == [
        "header",
        "timestamps",
        "meta",
        "updates",
    ]
    assert persisted["clipboard_summary"]["updates_limit"] == 3
    assert persisted["clipboard_summary"]["debug_status"] is False
    assert persisted["clipboard_summary"].get("inline_styles") is False
    assert persisted["demo_mode"] is True

    with app.app_context():
        updated_config = current_app.config["APP_CONFIG"]
        assert updated_config.demo_mode is True
        assert updated_config.priorities == ["Low", "Medium", "High", "Urgent"]
        assert current_app.config["DEMO_MODE"] is True

    new_app = create_app(config_path)
    with new_app.app_context():
        reloaded_config = current_app.config["APP_CONFIG"]
        assert reloaded_config.demo_mode is True
        assert reloaded_config.priorities == ["Low", "Medium", "High", "Urgent"]
        assert reloaded_config.hold_reasons == ["Awaiting info", "Review pending"]
        assert reloaded_config.clipboard_summary.html_sections == [
            "header",
            "timestamps",
            "meta",
        ]
        assert reloaded_config.clipboard_summary.text_sections == [
            "header",
            "timestamps",
            "meta",
            "updates",
        ]
        assert reloaded_config.clipboard_summary.updates_limit == 3
        assert reloaded_config.clipboard_summary.debug_status is False


def test_clipboard_debug_toggle_round_trip(tmp_path):
    config_data = _default_config()
    config_path = _write_config(tmp_path / "config.json", config_data)

    app = create_app(config_path)
    client = app.test_client()
    data = MultiDict(
        [
            ("default_submitted_by", config_data["default_submitted_by"]),
            ("priorities", "\n".join(config_data["priorities"])),
            ("hold_reasons", "\n".join(config_data["hold_reasons"])),
            ("workflow", "\n".join(config_data["workflow"])),
            (
                "updates_limit",
                str(config_data["clipboard_summary"]["updates_limit"]),
            ),
            ("clipboard_debug_status", "on"),
        ]
    )
    for section in config_data["clipboard_summary"]["html_sections"]:
        data.add("html_sections", section)
    for section in config_data["clipboard_summary"]["text_sections"]:
        data.add("text_sections", section)

    response = client.post(
        "/settings",
        data=data,
        follow_redirects=True,
    )

    assert response.status_code == 200

    persisted = json.loads(config_path.read_text())
    assert persisted["clipboard_summary"]["debug_status"] is True

    reloaded_app = create_app(config_path)
    with reloaded_app.app_context():
        reloaded_config = current_app.config["APP_CONFIG"]
        assert reloaded_config.clipboard_summary.debug_status is True
