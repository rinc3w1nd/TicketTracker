"""Utilities for loading and working with TicketTracker configuration."""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional

DEFAULT_CONFIG_NAME = "config.json"

DEFAULT_SECRET_KEY = "dev-secret-key-change-me"
DEFAULT_SUBMITTED_BY = "Support Team"


GRADIENT_STAGE_ORDER: List[str] = ["stage0", "stage1", "stage2", "stage3"]
GRADIENT_OVERDUE_KEY = "overdue"
DEFAULT_GRADIENT_COLORS: Dict[str, str] = {
    "stage0": "#bae6fd",
    "stage1": "#fde047",
    "stage2": "#fb923c",
    "stage3": "#ef4444",
    GRADIENT_OVERDUE_KEY: "#7f1d1d",
}

DEFAULT_TICKET_TITLE_COLOR = "#f8fafc"

DEFAULT_DUE_STAGE_DAYS: List[int] = [28, 21, 14, 7]
DEFAULT_PRIORITY_STAGE_DAYS: Dict[str, List[int]] = {
    "Low": [14, 21, 28, 35],
    "Medium": [10, 15, 20, 25],
    "High": [5, 7, 10, 14],
    "Critical": [2, 3, 5, 7],
}
DEFAULT_PRIORITY_STAGE_DAYS_FALLBACK: List[int] = [7, 14, 21, 28]
DEFAULT_BACKLOG_DUE_DAYS = 21


DEFAULT_CLIPBOARD_SUMMARY_SECTIONS: List[str] = [
    "header",
    "timestamps",
    "meta",
    "people",
    "description",
    "links",
    "notes",
    "tags",
    "updates",
]
DEFAULT_CLIPBOARD_SUMMARY: Dict[str, Any] = {
    "html_sections": list(DEFAULT_CLIPBOARD_SUMMARY_SECTIONS),
    "text_sections": list(DEFAULT_CLIPBOARD_SUMMARY_SECTIONS),
    "updates_limit": 1,
    "debug_status": False,
    "inline_styles": False,
}

DEFAULT_BEHAVIOR_CONFIG: Dict[str, Any] = {
    "auto_return_to_list": False,
}


DEFAULT_CONFIG: Dict[str, Any] = {
    "secret_key": DEFAULT_SECRET_KEY,
    "database": {"uri": "sqlite:///tickettracker.db"},
    "uploads": {"directory": "uploads"},
    "default_submitted_by": DEFAULT_SUBMITTED_BY,
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
        "default_due_days": DEFAULT_BACKLOG_DUE_DAYS,
    },
    "colors": {
        "ticket_title": DEFAULT_TICKET_TITLE_COLOR,
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
    "clipboard_summary": DEFAULT_CLIPBOARD_SUMMARY,
    "behavior": dict(DEFAULT_BEHAVIOR_CONFIG),
    "demo_mode": False,
}


@dataclass
class SLAConfig:
    """Service-level agreement thresholds used for coloring tickets."""

    due_stage_days: List[int] = field(default_factory=list)
    priority_stage_days: Dict[str, List[int]] = field(default_factory=dict)
    default_due_days: Optional[int] = DEFAULT_BACKLOG_DUE_DAYS

    def due_thresholds(self) -> List[int]:
        """Return descending day thresholds for due-date staging."""

        thresholds = [day for day in self.due_stage_days if isinstance(day, int)]
        thresholds.sort(reverse=True)
        return thresholds or list(DEFAULT_DUE_STAGE_DAYS)

    def priority_thresholds(self, priority: str) -> List[int]:
        """Return ascending day thresholds for backlog staging by priority."""

        raw_thresholds = self.priority_stage_days.get(priority)
        normalized = _normalize_stage_values(raw_thresholds)
        thresholds = _to_stage_thresholds(normalized)
        if thresholds:
            return thresholds

        default_thresholds = _normalize_stage_values(DEFAULT_PRIORITY_STAGE_DAYS.get(priority))
        thresholds = _to_stage_thresholds(default_thresholds)
        if thresholds:
            return thresholds

        fallback_thresholds = _normalize_stage_values(DEFAULT_PRIORITY_STAGE_DAYS_FALLBACK)
        return _to_stage_thresholds(fallback_thresholds)

    def remaining_days(self, priority: str, *, age_days: float) -> Optional[float]:
        """Return days remaining before a backlog ticket breaches its SLA."""

        thresholds = self.priority_thresholds(priority)
        if thresholds:
            limit = thresholds[-1]
        else:
            limit = self.default_due_days

        if limit is None:
            return None

        return float(limit) - float(age_days)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable representation of the SLA configuration."""

        return {
            "due_stage_days": list(self.due_stage_days),
            "priority_stage_days": {
                str(key): list(values) for key, values in self.priority_stage_days.items()
            },
            "default_due_days": self.default_due_days,
        }


@dataclass
class ColorConfig:
    """Color palette controls for different UI states."""

    gradient: Dict[str, str] = field(default_factory=dict)
    statuses: Dict[str, str] = field(default_factory=dict)
    priorities: Dict[str, str] = field(default_factory=dict)
    tags: Dict[str, str] = field(default_factory=dict)
    ticket_title: str = DEFAULT_TICKET_TITLE_COLOR

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

    def ticket_title_color(self) -> str:
        value = str(self.ticket_title or "").strip()
        return value or DEFAULT_TICKET_TITLE_COLOR

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable representation of the color palette."""

        return {
            "gradient": dict(self.gradient),
            "statuses": dict(self.statuses),
            "priorities": dict(self.priorities),
            "tags": dict(self.tags),
            "ticket_title": self.ticket_title,
        }


@dataclass
class ClipboardSummaryConfig:
    """Sections and limits used to build clipboard-friendly summaries."""

    html_sections: List[str] = field(default_factory=list)
    text_sections: List[str] = field(default_factory=list)
    updates_limit: int = DEFAULT_CLIPBOARD_SUMMARY["updates_limit"]
    debug_status: bool = False
    inline_styles: bool = False

    def sections_for_html(self) -> List[str]:
        sections = list(self.html_sections)
        if sections:
            return sections
        return list(DEFAULT_CLIPBOARD_SUMMARY["html_sections"])

    def sections_for_text(self) -> List[str]:
        sections = list(self.text_sections)
        if sections:
            return sections
        if self.html_sections:
            return list(self.html_sections)
        return list(DEFAULT_CLIPBOARD_SUMMARY["text_sections"])

    def max_updates(self) -> int:
        return max(0, int(self.updates_limit))

    def available_sections(self) -> List[str]:
        """Return a unique list of known clipboard sections."""

        seen: set[str] = set()
        ordered: List[str] = []
        for value in [
            *DEFAULT_CLIPBOARD_SUMMARY_SECTIONS,
            *self.html_sections,
            *self.text_sections,
        ]:
            key = str(value or "").strip().lower()
            if not key or key in seen:
                continue
            ordered.append(key)
            seen.add(key)
        return ordered

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable representation of clipboard options."""

        return {
            "html_sections": self.sections_for_html(),
            "text_sections": self.sections_for_text(),
            "updates_limit": int(self.updates_limit),
            "debug_status": bool(self.debug_status),
            "inline_styles": bool(self.inline_styles),
        }


@dataclass
class BehaviorConfig:
    """Configuration for post-action navigation behavior."""

    auto_return_to_list: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable representation of behavior settings."""

        return {"auto_return_to_list": bool(self.auto_return_to_list)}


@dataclass
class AppConfig:
    """Runtime configuration for the TicketTracker application."""

    secret_key: str
    database_uri: str
    uploads_directory: Path
    priorities: List[str]
    hold_reasons: List[str]
    workflow: List[str]
    default_submitted_by: str
    sla: SLAConfig
    colors: ColorConfig
    clipboard_summary: ClipboardSummaryConfig
    behavior: BehaviorConfig
    demo_mode: bool = False
    source_path: Optional[Path] = None

    @property
    def uploads_path(self) -> Path:
        return self.uploads_directory

    def to_json_dict(self) -> Dict[str, Any]:
        """Return a JSON-compatible dictionary representing the configuration."""

        return {
            "secret_key": self.secret_key,
            "database": {"uri": self.database_uri},
            "uploads": {"directory": str(self.uploads_directory)},
            "default_submitted_by": self.default_submitted_by,
            "priorities": list(self.priorities),
            "hold_reasons": list(self.hold_reasons),
            "workflow": list(self.workflow),
            "sla": self.sla.to_dict(),
            "colors": self.colors.to_dict(),
            "clipboard_summary": self.clipboard_summary.to_dict(),
            "behavior": self.behavior.to_dict(),
            "demo_mode": bool(self.demo_mode),
        }


def _coerce_non_negative_int(value: Any) -> Optional[int]:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number < 0:
        return None
    return number


def _coerce_string_list(raw_values: Any) -> List[str]:
    if raw_values is None:
        return []

    if isinstance(raw_values, Mapping):
        iterable = raw_values.values()
    elif isinstance(raw_values, Iterable) and not isinstance(raw_values, (str, bytes)):
        iterable = raw_values
    else:
        iterable = [raw_values]

    sections: List[str] = []
    for value in iterable:
        text = str(value or "").strip().lower()
        if not text or text in sections:
            continue
        sections.append(text)
    return sections


def _coerce_bool(value: Any, *, default: bool = False) -> bool:
    """Return a best-effort boolean interpretation of ``value``."""

    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        return default

    if value is None:
        return default

    if isinstance(value, (int, float)):
        return bool(value)

    return default


def _normalize_stage_values(raw_values: Any) -> List[int]:
    values: List[int] = []

    def _append(value: Any) -> None:
        number = _coerce_non_negative_int(value)
        if number is not None:
            values.append(number)

    if raw_values is None:
        return values

    if isinstance(raw_values, Mapping):
        consumed = set()
        for key in GRADIENT_STAGE_ORDER:
            if key in raw_values:
                _append(raw_values[key])
                consumed.add(key)
        for key, value in raw_values.items():
            if key in consumed:
                continue
            _append(value)
        return values

    if isinstance(raw_values, Iterable) and not isinstance(raw_values, (str, bytes)):
        for value in raw_values:
            _append(value)
        return values

    _append(raw_values)
    return values


def _to_stage_thresholds(values: Iterable[int]) -> List[int]:
    values_list = list(values)
    if not values_list:
        return []

    is_strictly_increasing = all(
        later > earlier for earlier, later in zip(values_list, values_list[1:])
    )
    if is_strictly_increasing:
        return list(values_list)

    thresholds: List[int] = []
    running_total = 0
    for value in values_list:
        running_total += value
        thresholds.append(running_total)
    return thresholds


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

    default_paths: List[Optional[Path]] = []
    if provided_path is None and env_path is None:
        default_paths.append(Path.cwd() / DEFAULT_CONFIG_NAME)
        default_paths.append(Path(__file__).resolve().parent.parent / DEFAULT_CONFIG_NAME)

    search_paths = [provided_path, env_path, *default_paths]

    config_file: Optional[Path] = None
    for candidate in search_paths:
        if candidate and candidate.exists():
            config_file = candidate
            break

    source_path: Optional[Path]
    if config_file:
        with config_file.open("r", encoding="utf-8") as fh:
            loaded_data = json.load(fh)
        base_path = config_file.parent
        source_path = config_file
    else:
        loaded_data = {}
        fallback_path = provided_path or env_path
        if fallback_path is None:
            fallback_path = default_paths[0] if default_paths else Path.cwd() / DEFAULT_CONFIG_NAME
        source_path = fallback_path
        base_path = source_path.parent

    if source_path is not None:
        source_path = source_path.resolve()

    merged: Dict[str, Any] = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    _merge_dict(merged, loaded_data)

    default_submitted_by_value = merged.get(
        "default_submitted_by", DEFAULT_SUBMITTED_BY
    )
    if isinstance(default_submitted_by_value, str):
        default_submitted_by = (
            default_submitted_by_value.strip() or DEFAULT_SUBMITTED_BY
        )
    elif default_submitted_by_value is None:
        default_submitted_by = DEFAULT_SUBMITTED_BY
    else:
        default_submitted_by = (
            str(default_submitted_by_value).strip() or DEFAULT_SUBMITTED_BY
        )

    sla_config = merged.get("sla", {})
    colors_config = merged.get("colors", {})
    clipboard_summary_config = merged.get("clipboard_summary", {})
    behavior_config = merged.get("behavior", {})

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

    default_due_days = _coerce_non_negative_int(sla_config.get("default_due_days"))
    if default_due_days is None:
        default_due_days = _coerce_non_negative_int(
            DEFAULT_CONFIG.get("sla", {}).get("default_due_days")
        )

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

    raw_ticket_title_color = colors_config.get("ticket_title", DEFAULT_TICKET_TITLE_COLOR)
    if isinstance(raw_ticket_title_color, str):
        ticket_title_color = raw_ticket_title_color.strip() or DEFAULT_TICKET_TITLE_COLOR
    elif raw_ticket_title_color is None:
        ticket_title_color = DEFAULT_TICKET_TITLE_COLOR
    else:
        ticket_title_color = str(raw_ticket_title_color).strip() or DEFAULT_TICKET_TITLE_COLOR

    html_sections = _coerce_string_list(
        clipboard_summary_config.get("html_sections")
    )
    text_sections = _coerce_string_list(
        clipboard_summary_config.get("text_sections")
    )
    updates_limit = _coerce_non_negative_int(
        clipboard_summary_config.get("updates_limit")
    )
    if updates_limit is None:
        updates_limit = int(DEFAULT_CLIPBOARD_SUMMARY["updates_limit"])

    debug_status = _coerce_bool(
        clipboard_summary_config.get("debug_status"),
        default=bool(DEFAULT_CLIPBOARD_SUMMARY.get("debug_status", False)),
    )
    inline_styles = _coerce_bool(
        clipboard_summary_config.get("inline_styles"),
        default=bool(DEFAULT_CLIPBOARD_SUMMARY.get("inline_styles", False)),
    )

    resolved_html_sections = (
        html_sections if html_sections else list(DEFAULT_CLIPBOARD_SUMMARY["html_sections"])
    )
    resolved_text_sections = (
        text_sections
        if text_sections
        else (html_sections if html_sections else list(DEFAULT_CLIPBOARD_SUMMARY["text_sections"]))
    )

    clipboard_summary = ClipboardSummaryConfig(
        html_sections=resolved_html_sections,
        text_sections=resolved_text_sections,
        updates_limit=updates_limit,
        debug_status=debug_status,
        inline_styles=inline_styles,
    )

    demo_mode = _coerce_bool(merged.get("demo_mode"), default=False)

    if not isinstance(behavior_config, Mapping):
        behavior_config = {}

    auto_return_to_list = _coerce_bool(
        behavior_config.get("auto_return_to_list"),
        default=bool(DEFAULT_BEHAVIOR_CONFIG.get("auto_return_to_list", False)),
    )
    behavior = BehaviorConfig(auto_return_to_list=auto_return_to_list)

    return AppConfig(
        secret_key=secret_key,
        database_uri=database_uri,
        uploads_directory=uploads_directory,
        priorities=list(merged.get("priorities", [])),
        hold_reasons=list(merged.get("hold_reasons", [])),
        workflow=list(merged.get("workflow", [])),
        default_submitted_by=default_submitted_by,
        sla=SLAConfig(
            due_stage_days=due_stage_days,
            priority_stage_days=priority_stage_days,
            default_due_days=default_due_days,
        ),
        colors=ColorConfig(
            gradient=dict(colors_config.get("gradient", {})),
            statuses=dict(colors_config.get("statuses", {})),
            priorities=dict(colors_config.get("priorities", {})),
            tags=dict(colors_config.get("tags", {})),
            ticket_title=ticket_title_color,
        ),
        clipboard_summary=clipboard_summary,
        behavior=behavior,
        demo_mode=demo_mode,
        source_path=source_path,
    )


def save_config(config: AppConfig, path: Optional[os.PathLike[str] | str] = None) -> Path:
    """Persist ``config`` to disk and return the resolved path used."""

    target_path = Path(path) if path is not None else config.source_path
    if target_path is None:
        raise ValueError("Configuration path is unknown; provide a destination when saving.")

    target_path = target_path.resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)

    payload = config.to_json_dict()
    with target_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")

    config.source_path = target_path
    return target_path
