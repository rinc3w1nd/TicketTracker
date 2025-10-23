"""Tests for the configuration settings workflow."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flask import current_app
from werkzeug.datastructures import MultiDict

from tickettracker.app import create_app
from tickettracker.config import (
    DEFAULT_CONFIG,
    DEFAULT_PRIORITY_STAGE_DAYS_FALLBACK,
    load_config,
)


def _write_config(target: Path, data: dict) -> Path:
    target.write_text(json.dumps(data, indent=2))
    return target


def _default_config() -> dict:
    return json.loads(json.dumps(DEFAULT_CONFIG))


def _settings_form_data(config_data: dict, **overrides: object) -> dict:
    sla_config = config_data.get("sla", {})
    default_due_days = sla_config.get("default_due_days")
    due_stage_days = [str(value) for value in sla_config.get("due_stage_days", [])]
    priority_stage_days = {
        str(priority): list(values)
        for priority, values in sla_config.get("priority_stage_days", {}).items()
    }
    base_due_stage_days = DEFAULT_CONFIG.get("sla", {}).get("due_stage_days", [])
    stage_lengths = [len(due_stage_days), len(base_due_stage_days)]
    stage_lengths.extend(len(values) for values in priority_stage_days.values())
    stage_count = max(stage_lengths) if stage_lengths else len(base_due_stage_days)
    if stage_count <= 0:
        stage_count = 1

    due_stage_payload = list(due_stage_days)
    if len(due_stage_payload) < stage_count:
        due_stage_payload.extend([""] * (stage_count - len(due_stage_payload)))

    base_priority_defaults = DEFAULT_CONFIG.get("sla", {}).get(
        "priority_stage_days", {}
    )

    payload = {
        "default_submitted_by": config_data["default_submitted_by"],
        "priorities": "\n".join(config_data["priorities"]),
        "hold_reasons": "\n".join(config_data["hold_reasons"]),
        "workflow": "\n".join(config_data["workflow"]),
        "html_sections": "\n".join(config_data["clipboard_summary"]["html_sections"]),
        "text_sections": "\n".join(config_data["clipboard_summary"]["text_sections"]),
        "updates_limit": str(config_data["clipboard_summary"]["updates_limit"]),
        "default_due_days": "" if default_due_days is None else str(default_due_days),
        "due_stage_days": due_stage_payload,
    }

    priority_values: dict[str, list[str]] = {}
    for priority in config_data.get("priorities", []):
        configured = priority_stage_days.get(priority)
        if configured:
            values = [str(value) for value in configured]
        else:
            fallback = base_priority_defaults.get(priority)
            if fallback is None:
                fallback = DEFAULT_PRIORITY_STAGE_DAYS_FALLBACK
            values = [str(value) for value in fallback]
        if len(values) < stage_count:
            values.extend([""] * (stage_count - len(values)))
        priority_values[priority] = values

    for priority, values in priority_values.items():
        payload[f"priority_stage_days[{priority}]"] = values

    payload.update(overrides)
    return payload


def test_load_config_records_source_path(tmp_path):
    config_data = _default_config()
    config_data["database"]["uri"] = "sqlite:///:memory:"
    config_path = _write_config(tmp_path / "config.json", config_data)

    config = load_config(config_path)

    assert config.source_path == config_path.resolve()
    payload = config.to_json_dict()
    assert payload["demo_mode"] is False
    assert payload["behavior"]["auto_return_to_list"] is False
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
    form_payload = _settings_form_data(
        config_data,
        default_submitted_by="Operations Team",
        priorities="Low\nMedium\nHigh\nUrgent",
        hold_reasons="Awaiting info\nReview pending",
        workflow="New\nActive\nDone",
        html_sections="header\ntimestamps\nsummary",
        text_sections="header\ntimestamps\nsummary\nnotes",
        updates_limit="3",
        demo_mode="on",
        auto_return_to_list="on",
    )

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
                ("auto_return_to_list", "on"),
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
    assert persisted["behavior"]["auto_return_to_list"] is True

    with app.app_context():
        updated_config = current_app.config["APP_CONFIG"]
        assert updated_config.demo_mode is True
        assert updated_config.priorities == ["Low", "Medium", "High", "Urgent"]
        assert updated_config.auto_return_to_list is True
        assert current_app.config["DEMO_MODE"] is True

    new_app = create_app(config_path)
    with new_app.app_context():
        reloaded_config = current_app.config["APP_CONFIG"]
        assert reloaded_config.demo_mode is True
        assert reloaded_config.priorities == ["Low", "Medium", "High", "Urgent"]
        assert reloaded_config.hold_reasons == ["Awaiting info", "Review pending"]
        assert reloaded_config.auto_return_to_list is True
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


def test_update_sla_settings(tmp_path):
    config_data = _default_config()
    config_path = _write_config(tmp_path / "config.json", config_data)

    app = create_app(config_path)
    client = app.test_client()

    due_stage_values = ["30", "20", "10", "5"]
    priority_stage_values = {
        "Low": ["15", "20", "25", "30"],
        "Medium": ["12", "18", "22", "28"],
        "High": ["8", "12", "16", "20"],
        "Critical": ["4", "6", "8", "10"],
    }

    data_items: List[tuple[str, str]] = [
        ("default_submitted_by", config_data["default_submitted_by"]),
        ("priorities", "\n".join(config_data["priorities"])),
        ("hold_reasons", "\n".join(config_data["hold_reasons"])),
        ("workflow", "\n".join(config_data["workflow"])),
        ("updates_limit", str(config_data["clipboard_summary"]["updates_limit"])),
        ("default_due_days", "35"),
    ]

    for section in config_data["clipboard_summary"]["html_sections"]:
        data_items.append(("html_sections", section))
    for section in config_data["clipboard_summary"]["text_sections"]:
        data_items.append(("text_sections", section))

    for value in due_stage_values:
        data_items.append(("due_stage_days", value))

    for priority, values in priority_stage_values.items():
        for value in values:
            data_items.append((f"priority_stage_days[{priority}]", value))

    response = client.post(
        "/settings",
        data=MultiDict(data_items),
        follow_redirects=True,
    )

    assert response.status_code == 200

    persisted = json.loads(config_path.read_text())
    assert persisted["sla"]["default_due_days"] == 35
    assert persisted["sla"]["due_stage_days"] == [30, 20, 10, 5]
    assert persisted["sla"]["priority_stage_days"]["Low"] == [15, 20, 25, 30]
    assert persisted["sla"]["priority_stage_days"]["Critical"] == [4, 6, 8, 10]

    with app.app_context():
        sla_config = current_app.config["APP_CONFIG"].sla
        assert sla_config.default_due_days == 35
        assert sla_config.due_stage_days == [30, 20, 10, 5]
        assert sla_config.priority_stage_days["Medium"] == [12, 18, 22, 28]


def test_update_color_palette(tmp_path):
    config_data = _default_config()
    config_path = _write_config(tmp_path / "config.json", config_data)

    app = create_app(config_path)
    client = app.test_client()

    payload = _settings_form_data(config_data)
    payload.update(
        {
            "colors[ticket_title]": "#ddeeff",
            "colors[gradient][stage0]": "#112233",
            "colors[gradient][stage1]": "#223344",
            "colors[gradient][stage3]": "#556677",
            "colors[gradient][overdue]": "#778899",
            "colors[statuses][resolved]": "#336699",
            "colors[priorities][Medium]": "#00aa00",
            "colors[priorities][High]": "#abc",
            "colors[priorities][Critical]": "#123456",
            "colors[tags][background]": "#010203",
            "colors[tags][text]": "#fefefe",
        }
    )

    response = client.post(
        "/settings",
        data=payload,
        follow_redirects=True,
    )

    assert response.status_code == 200

    persisted = json.loads(config_path.read_text())
    colors = persisted["colors"]
    defaults = DEFAULT_CONFIG["colors"]

    assert colors["ticket_title"] == "#DDEEFF"
    assert colors["gradient"]["stage0"] == "#112233"
    assert colors["gradient"]["stage1"] == "#223344"
    assert colors["gradient"]["stage2"] == defaults["gradient"]["stage2"].upper()
    assert colors["gradient"]["stage3"] == "#556677"
    assert colors["gradient"]["overdue"] == "#778899"
    assert colors["statuses"]["resolved"] == "#336699"
    assert colors["statuses"]["on_hold"] == defaults["statuses"]["on_hold"].upper()
    assert colors["priorities"]["High"] == "#AABBCC"
    assert colors["priorities"]["Medium"] == "#00AA00"
    assert colors["priorities"]["Critical"] == "#123456"
    assert colors["priorities"]["Low"] == defaults["priorities"]["Low"].upper()
    assert colors["tags"]["background"] == "#010203"
    assert colors["tags"]["text"] == "#FEFEFE"

    with app.app_context():
        updated_config = current_app.config["APP_CONFIG"]
        assert updated_config.colors.ticket_title == "#DDEEFF"
        assert updated_config.colors.gradient_color("stage2") == defaults["gradient"][
            "stage2"
        ].upper()
        assert updated_config.colors.statuses["resolved"] == "#336699"
        assert updated_config.colors.priorities["High"] == "#AABBCC"

    reloaded_app = create_app(config_path)
    with reloaded_app.app_context():
        reloaded_config = current_app.config["APP_CONFIG"]
        assert reloaded_config.colors.ticket_title == "#DDEEFF"
        assert reloaded_config.colors.gradient["stage0"] == "#112233"
        assert reloaded_config.colors.statuses["on_hold"] == defaults["statuses"][
            "on_hold"
        ].upper()
        assert reloaded_config.colors.priorities["Medium"] == "#00AA00"

def test_settings_redirects_to_settings_when_auto_return_disabled(tmp_path):
    config_data = _default_config()
    config_path = _write_config(tmp_path / "config.json", config_data)

    app = create_app(config_path)
    client = app.test_client()

    response = client.post(
        "/settings?compact=0",
        data=_settings_form_data(config_data),
        follow_redirects=False,
    )

    assert response.status_code == 302
    location = urlparse(response.headers["Location"])
    assert location.path == "/settings"
    assert parse_qs(location.query).get("compact") == ["0"]

    with app.app_context():
        assert current_app.config["APP_CONFIG"].auto_return_to_list is False


def test_settings_redirects_to_ticket_list_when_auto_return_enabled(tmp_path):
    config_data = _default_config()
    config_path = _write_config(tmp_path / "config.json", config_data)

    app = create_app(config_path)
    client = app.test_client()

    response = client.post(
        "/settings?compact=0",
        data=_settings_form_data(config_data, auto_return_to_list="on"),
        follow_redirects=False,
    )

    assert response.status_code == 302
    location = urlparse(response.headers["Location"])
    assert location.path == "/"
    assert parse_qs(location.query).get("compact") == ["0"]

    with app.app_context():
        assert current_app.config["APP_CONFIG"].auto_return_to_list is True


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
