import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flask import current_app

from tickettracker.app import create_app
from tickettracker.config import DEFAULT_CONFIG, GRADIENT_STAGE_ORDER
from tickettracker.views.tickets import _compute_ticket_color


def _write_config(target: Path, data: dict) -> Path:
    target.write_text(json.dumps(data, indent=2))
    return target


def _default_config() -> dict:
    return json.loads(json.dumps(DEFAULT_CONFIG))


def _resolve_stage_index(config, color: str) -> int | None:
    normalized = color.upper()
    for index, key in enumerate(GRADIENT_STAGE_ORDER):
        stage_color = config.colors.gradient_color(key)
        if stage_color.upper() == normalized:
            return index
    overdue_color = config.colors.gradient_overdue_color()
    if overdue_color.upper() == normalized:
        return len(GRADIENT_STAGE_ORDER)
    return None


def _stage_for_days(config, days_out: float) -> int | None:
    now = datetime.utcnow()
    ticket = SimpleNamespace(
        due_date=now + timedelta(days=days_out),
        created_at=None,
        age_reference_date=None,
        priority="Low",
        status=None,
    )
    color = _compute_ticket_color(ticket, config)
    return _resolve_stage_index(config, color)


def test_due_stage_thresholds_follow_zone_labels(tmp_path):
    config_data = _default_config()
    config_path = _write_config(tmp_path / "config.json", config_data)
    app = create_app(config_path)

    with app.app_context():
        config = current_app.config["APP_CONFIG"]

        assert config.sla.due_thresholds() == [7, 14, 21, 28]

        assert _stage_for_days(config, 35) == 0
        assert _stage_for_days(config, 24) == 0
        assert _stage_for_days(config, 19) == 1
        assert _stage_for_days(config, 12) == 2
        assert _stage_for_days(config, 6) == 3


def test_due_stage_thresholds_sort_unsorted_values(tmp_path):
    config_data = _default_config()
    config_data.setdefault("sla", {})["due_stage_days"] = [30, 10, 20, 5]
    config_path = _write_config(tmp_path / "config.json", config_data)
    app = create_app(config_path)

    with app.app_context():
        config = current_app.config["APP_CONFIG"]

        assert config.sla.due_thresholds() == [5, 10, 20, 30]

        assert _stage_for_days(config, 32) == 0
        assert _stage_for_days(config, 18) == 1
        assert _stage_for_days(config, 9) == 2
        assert _stage_for_days(config, 4) == 3
