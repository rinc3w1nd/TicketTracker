"""Utilities for loading and working with TicketTracker configuration."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, MutableMapping, Optional

DEFAULT_CONFIG_NAME = "config.json"

DEFAULT_SECRET_KEY = "dev-secret-key-change-me"


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
        "due_soon_hours": 24,
        "overdue_grace_minutes": 0,
        "priority_open_days": {"Low": 7, "Medium": 5, "High": 3, "Critical": 1},
    },
    "colors": {
        "gradient": {
            "safe": "#1e90ff",
            "warning": "#ffa502",
            "overdue": "#ff4757",
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

    due_soon_hours: int = 24
    overdue_grace_minutes: int = 0
    priority_open_days: Dict[str, int] = field(default_factory=dict)


@dataclass
class ColorConfig:
    """Color palette controls for different UI states."""

    gradient: Dict[str, str] = field(default_factory=dict)
    statuses: Dict[str, str] = field(default_factory=dict)
    priorities: Dict[str, str] = field(default_factory=dict)
    tags: Dict[str, str] = field(default_factory=dict)


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
            due_soon_hours=int(sla_config.get("due_soon_hours", 24)),
            overdue_grace_minutes=int(sla_config.get("overdue_grace_minutes", 0)),
            priority_open_days={k: int(v) for k, v in sla_config.get("priority_open_days", {}).items()},
        ),
        colors=ColorConfig(
            gradient=dict(colors_config.get("gradient", {})),
            statuses=dict(colors_config.get("statuses", {})),
            priorities=dict(colors_config.get("priorities", {})),
            tags=dict(colors_config.get("tags", {})),
        ),
    )
