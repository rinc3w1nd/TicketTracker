"""Utilities for loading and working with TicketTracker configuration."""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, MutableMapping, Optional

DEFAULT_CONFIG_NAME = "config.json"

DEFAULT_SECRET_KEY = "dev-secret-key-change-me"


GRADIENT_STAGE_ORDER: List[str] = ["stage0", "stage1", "stage2", "stage3"]
GRADIENT_OVERDUE_KEY = "overdue"
DEFAULT_GRADIENT_COLORS: Dict[str, str] = {
    "stage0": "#bae6fd",
    "stage1": "#fde047",
    "stage2": "#fb923c",
    "stage3": "#ef4444",
    GRADIENT_OVERDUE_KEY: "#7f1d1d",
}

DEFAULT_DUE_STAGE_DAYS: List[int] = [28, 21, 14, 7]
DEFAULT_PRIORITY_STAGE_DAYS: Dict[str, List[int]] = {
    "Low": [14, 21, 28, 35],
    "Medium": [10, 15, 20, 25],
    "High": [5, 7, 10, 14],
    "Critical": [2, 3, 5, 7],
}
DEFAULT_PRIORITY_STAGE_DAYS_FALLBACK: List[int] = [7, 14, 21, 28]


DEFAULT_CONFIG: Dict[str, Any] = {
    "secret_key": DEFAULT_SECRET_KEY,
    "database": {"uri": "sqlite:///tickettracker.db"},
    "uploads": {"directory": "uploads"},
    "priorities": ["Low", "Medium", "High", "Critical"],
    "hold_reasons": [
        "Awaiting customer response",
        "Blocked by dependency",
        "Pending scheduled work",
        "Researching solution",
    ],
    "workflow": ["Open", "In Progress", "On Hold", "Resolved", "Closed", "Cancelled"],
    "sla": {
        "due_stage_days": DEFAULT_DUE_STAGE_DAYS,
        "priority_stage_days": DEFAULT_PRIORITY_STAGE_DAYS,
    },
    "colors": {
        "gradient": {
            **DEFAULT_GRADIENT_COLORS,
        },
        "statuses": {
            "on_hold": "#9c88ff",
            "resolved": "#2ed573",
            "closed": "#57606f",
            "cancelled": "#747d8c",
        },
        "priorities": {
            "Low": "#3b82f6",
            "Medium": "#facc15",
            "High": "#f97316",
            "Critical": "#ef4444",
        },
        "tags": {
            "background": "#2f3542",
            "text": "#f1f2f6",
        },
    },
}


@dataclass
class SLAConfig:
    """Service-level agreement thresholds used for coloring tickets."""

    due_stage_days: List[int] = field(default_factory=list)
    priority_stage_days: Dict[str, List[int]] = field(default_factory=dict)

    def due_thresholds(self) -> List[int]:
        """Return descending day thresholds for due-date staging."""

        thresholds = [day for day in self.due_stage_days if isinstance(day, int)]
        thresholds.sort(reverse=True)
        return thresholds or list(DEFAULT_DUE_STAGE_DAYS)

    def priority_thresholds(self, priority: str) -> List[int]:
        """Return ascending day thresholds for backlog staging by priority."""

        raw_thresholds = self.priority_stage_days.get(priority)
        if raw_thresholds:
            thresholds = [day for day in raw_thresholds if isinstance(day, int)]
            thresholds = [day for day in thresholds if day >= 0]
            thresholds.sort()
            if thresholds:
                return thresholds

        default_thresholds = DEFAULT_PRIORITY_STAGE_DAYS.get(priority)
        if default_thresholds:
            return list(default_thresholds)

        return list(DEFAULT_PRIORITY_STAGE_DAYS_FALLBACK)


@dataclass
class ColorConfig:
    """Color palette controls for different UI states."""

    gradient: Dict[str, str] = field(default_factory=dict)
    statuses: Dict[str, str] = field(default_factory=dict)
    priorities: Dict[str, str] = field(default_factory=dict)
    tags: Dict[str, str] = field(default_factory=dict)

    def gradient_color(self, key: str) -> str:
        if key in DEFAULT_GRADIENT_COLORS:
            return self.gradient.get(key, DEFAULT_GRADIENT_COLORS[key])
        return self.gradient.get(key, DEFAULT_GRADIENT_COLORS[GRADIENT_STAGE_ORDER[0]])

    def gradient_stage_color(self, stage_index: int) -> str:
        bounded_index = max(0, min(stage_index, len(GRADIENT_STAGE_ORDER) - 1))
        key = GRADIENT_STAGE_ORDER[bounded_index]
        return self.gradient_color(key)

    def gradient_overdue_color(self) -> str:
        return self.gradient_color(GRADIENT_OVERDUE_KEY)


@dataclass
class AppConfig:
    """Runtime configuration for the TicketTracker application."""

    secret_key: str
    database_uri: str
    uploads_directory: Path
    priorities: List[str]
    hold_reasons: List[str]
    workflow: List[str]
    sla: SLAConfig
    colors: ColorConfig

    @property
    def uploads_path(self) -> Path:
        return self.uploads_directory


def _coerce_non_negative_int(value: Any) -> Optional[int]:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number < 0:
        return None
    return number


def _legacy_stage_thresholds(limit: int) -> List[int]:
    if limit <= 0:
        return []

    quarter = max(1, math.ceil(limit / 4))
    half = max(quarter, math.ceil(limit / 2))
    three_quarter = max(half, math.ceil(limit * 3 / 4))
    final = max(three_quarter, limit)
    return [quarter, half, three_quarter, final]


def _merge_dict(base: MutableMapping[str, Any], overlay: Mapping[str, Any]) -> MutableMapping[str, Any]:
    for key, value in overlay.items():
        if isinstance(value, Mapping) and isinstance(base.get(key), MutableMapping):
            base[key] = _merge_dict(base[key], value)
        else:
            base[key] = value
    return base


def _resolve_database_uri(raw_uri: str, base_path: Path) -> str:
    if raw_uri.startswith("sqlite:///") and not raw_uri.startswith("sqlite:////"):
        relative_path = raw_uri.replace("sqlite:///", "", 1)
        db_path = Path(relative_path)
        if not db_path.is_absolute():
            db_path = (base_path / db_path).resolve()
        return f"sqlite:///{db_path}"
    return raw_uri


def _resolve_upload_directory(raw_directory: str, base_path: Path) -> Path:
    upload_path = Path(raw_directory)
    if not upload_path.is_absolute():
        upload_path = (base_path / upload_path).resolve()
    return upload_path


def load_config(config_path: Optional[os.PathLike[str] | str] = None) -> AppConfig:
    """Load application configuration from JSON, applying defaults as needed."""

    provided_path = Path(config_path) if config_path else None
    env_path = Path(os.environ["TICKETTRACKER_CONFIG"]) if "TICKETTRACKER_CONFIG" in os.environ else None

    search_paths = [provided_path, env_path]
    if provided_path is None and env_path is None:
        search_paths.append(Path.cwd() / DEFAULT_CONFIG_NAME)
        search_paths.append(Path(__file__).resolve().parent.parent / DEFAULT_CONFIG_NAME)

    config_file: Optional[Path] = None
    for candidate in search_paths:
        if candidate and candidate.exists():
            config_file = candidate
            break

    if config_file:
        with config_file.open("r", encoding="utf-8") as fh:
            loaded_data = json.load(fh)
        base_path = config_file.parent
    else:
        loaded_data = {}
        base_path = Path.cwd()

    merged: Dict[str, Any] = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    _merge_dict(merged, loaded_data)

    sla_config = merged.get("sla", {})
    colors_config = merged.get("colors", {})

    raw_due_stage_days = sla_config.get("due_stage_days", [])
    due_stage_days: List[int] = []
    if isinstance(raw_due_stage_days, (list, tuple)):
        for value in raw_due_stage_days:
            coerced = _coerce_non_negative_int(value)
            if coerced is not None:
                due_stage_days.append(coerced)

    raw_priority_stage_days = sla_config.get("priority_stage_days", {})
    priority_stage_days: Dict[str, List[int]] = {}
    if isinstance(raw_priority_stage_days, Mapping):
        for priority, values in raw_priority_stage_days.items():
            if not isinstance(values, (list, tuple)):
                continue
            sanitized: List[int] = []
            for value in values:
                coerced = _coerce_non_negative_int(value)
                if coerced is not None:
                    sanitized.append(coerced)
            if sanitized:
                priority_stage_days[str(priority)] = sanitized

    legacy_priority_open = sla_config.get("priority_open_days", {})
    if isinstance(legacy_priority_open, Mapping):
        for priority, value in legacy_priority_open.items():
            coerced = _coerce_non_negative_int(value)
            if coerced is None:
                continue
            priority_key = str(priority)
            if priority_key not in priority_stage_days:
                thresholds = _legacy_stage_thresholds(coerced)
                if thresholds:
                    priority_stage_days[priority_key] = thresholds

    database_uri = _resolve_database_uri(merged.get("database", {}).get("uri", "sqlite:///tickettracker.db"), base_path)
    uploads_directory = _resolve_upload_directory(merged.get("uploads", {}).get("directory", "uploads"), base_path)
    secret_key = os.environ.get("TICKETTRACKER_SECRET_KEY") or str(merged.get("secret_key", DEFAULT_SECRET_KEY))

    return AppConfig(
        secret_key=secret_key,
        database_uri=database_uri,
        uploads_directory=uploads_directory,
        priorities=list(merged.get("priorities", [])),
        hold_reasons=list(merged.get("hold_reasons", [])),
        workflow=list(merged.get("workflow", [])),
        sla=SLAConfig(
            due_stage_days=due_stage_days,
            priority_stage_days=priority_stage_days,
        ),
        colors=ColorConfig(
            gradient=dict(colors_config.get("gradient", {})),
            statuses=dict(colors_config.get("statuses", {})),
            priorities=dict(colors_config.get("priorities", {})),
            tags=dict(colors_config.get("tags", {})),
        ),
    )
