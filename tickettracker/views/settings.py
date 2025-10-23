"""Application settings management views."""
from __future__ import annotations

from dataclasses import replace
from copy import deepcopy
from typing import Dict, List, Mapping, Tuple

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from ..config import (
    AppConfig,
    DEFAULT_CONFIG,
    DEFAULT_GRADIENT_COLORS,
    DEFAULT_PRIORITY_COLORS,
    DEFAULT_PRIORITY_STAGE_DAYS_FALLBACK,
    DEFAULT_STATUS_COLORS,
    DEFAULT_TAG_COLORS,
    DEFAULT_TICKET_TITLE_COLOR,
    GRADIENT_OVERDUE_KEY,
    GRADIENT_STAGE_ORDER,
    normalize_hex_color,
    save_config,
)
from ..demo import DemoModeError, get_demo_manager
from ..summary import CLIPBOARD_SUMMARY_SECTION_DESCRIPTIONS


settings_bp = Blueprint("settings", __name__)


_DEFAULT_STAGE_LABELS = [
    "Comfort Zone",
    "Attention Zone",
    "Action Zone",
    "Fire Zone",
]


def _stage_labels(stage_count: int) -> List[str]:
    """Return human-friendly labels for SLA stages."""

    if stage_count <= 0:
        return []

    labels: List[str] = []
    for index in range(stage_count):
        if index < len(_DEFAULT_STAGE_LABELS):
            labels.append(_DEFAULT_STAGE_LABELS[index])
        else:
            labels.append(f"Stage {index + 1}")
    return labels


def _stage_index_from_key(key: str) -> int | None:
    """Return the numeric index for gradient stage keys (e.g. ``stage2``)."""

    prefix = "stage"
    if key.startswith(prefix):
        suffix = key[len(prefix) :]
        if suffix.isdigit():
            return int(suffix)
    return None


def _app_config() -> AppConfig:
    return current_app.config["APP_CONFIG"]


def _persist_config(updated_config: AppConfig) -> bool:
    try:
        save_config(updated_config)
    except ValueError:
        flash(
            "Unable to determine configuration file path; changes were not saved.",
            "error",
        )
        return False

    current_app.config["APP_CONFIG"] = updated_config
    current_app.config["DEMO_MODE"] = updated_config.demo_mode
    return True


def _is_compact_mode() -> bool:
    value = request.args.get("compact")
    if value is None:
        return True

    normalized = value.strip().lower()
    if normalized in {"0", "false", "no", "off"}:
        return False
    if normalized in {"1", "true", "yes", "on"}:
        return True
    return True


def _compact_query_value(compact_mode: bool) -> str:
    return "1" if compact_mode else "0"


def _clipboard_section_options(config: AppConfig) -> List[Tuple[str, str]]:
    """Return ordered clipboard sections paired with their descriptions."""

    options: List[Tuple[str, str]] = list(
        CLIPBOARD_SUMMARY_SECTION_DESCRIPTIONS.items()
    )
    seen = {section for section, _ in options}
    custom_description = "Custom clipboard section configured in your settings."

    for section in config.clipboard_summary.available_sections():
        if section in seen:
            continue
        options.append((section, custom_description))
        seen.add(section)

    return options


def _build_compact_toggle_url(endpoint: str, compact_mode: bool, **values: object) -> str:
    query_args: Dict[str, List[str]] = {key: list(items) for key, items in request.args.lists()}
    query_args["compact"] = [_compact_query_value(not compact_mode)]

    flattened: Dict[str, object] = {
        key: value if len(value) != 1 else value[0]
        for key, value in query_args.items()
    }
    return url_for(endpoint, **values, **flattened)


def _parse_multiline_field(raw_value: str | None) -> List[str]:
    if not raw_value:
        return []

    entries: List[str] = []
    seen: set[str] = set()
    for segment in raw_value.replace(",", "\n").splitlines():
        text = segment.strip()
        if not text or text in seen:
            continue
        entries.append(text)
        seen.add(text)
    return entries


def _color_palette_defaults(config: AppConfig) -> Dict[str, Dict[str, str] | str]:
    """Return default color values for palette sections, including fallbacks."""

    primary_fallback = (
        normalize_hex_color(DEFAULT_GRADIENT_COLORS[GRADIENT_STAGE_ORDER[0]])
        or DEFAULT_GRADIENT_COLORS[GRADIENT_STAGE_ORDER[0]]
    )

    gradient_defaults: Dict[str, str] = {}
    for key in [*GRADIENT_STAGE_ORDER, GRADIENT_OVERDUE_KEY]:
        default_value = normalize_hex_color(DEFAULT_GRADIENT_COLORS.get(key))
        gradient_defaults[str(key)] = default_value or primary_fallback
    for key in config.colors.gradient.keys():
        key_str = str(key)
        if key_str not in gradient_defaults:
            gradient_defaults[key_str] = primary_fallback

    status_defaults: Dict[str, str] = {}
    for key, value in DEFAULT_STATUS_COLORS.items():
        status_defaults[str(key)] = normalize_hex_color(value) or primary_fallback
    for key in config.colors.statuses.keys():
        key_str = str(key)
        if key_str not in status_defaults:
            status_defaults[key_str] = primary_fallback

    priority_defaults: Dict[str, str] = {}
    base_priority_defaults = {
        str(priority): color for priority, color in DEFAULT_PRIORITY_COLORS.items()
    }
    for priority in config.priorities:
        key_str = str(priority)
        default_value = base_priority_defaults.get(key_str)
        normalized = normalize_hex_color(default_value)
        priority_defaults[key_str] = normalized or primary_fallback
    for key in config.colors.priorities.keys():
        key_str = str(key)
        if key_str not in priority_defaults:
            default_value = base_priority_defaults.get(key_str)
            normalized = normalize_hex_color(default_value)
            priority_defaults[key_str] = normalized or primary_fallback

    tag_defaults: Dict[str, str] = {}
    for key, value in DEFAULT_TAG_COLORS.items():
        tag_defaults[str(key)] = normalize_hex_color(value) or primary_fallback
    for key in config.colors.tags.keys():
        key_str = str(key)
        if key_str not in tag_defaults:
            tag_defaults[key_str] = primary_fallback

    ticket_title_default = (
        normalize_hex_color(DEFAULT_TICKET_TITLE_COLOR)
        or DEFAULT_TICKET_TITLE_COLOR
    )

    return {
        "ticket_title": ticket_title_default,
        "gradient": gradient_defaults,
        "statuses": status_defaults,
        "priorities": priority_defaults,
        "tags": tag_defaults,
    }


def _color_palette_display(config: AppConfig) -> Dict[str, Dict[str, Dict[str, str]]]:
    """Return palette data structure used to populate the settings form."""

    defaults = _color_palette_defaults(config)

    palette: Dict[str, Dict[str, Dict[str, str]]] = {
        "ticket_title": {
            "value": defaults["ticket_title"],
            "text": defaults["ticket_title"],
            "default": defaults["ticket_title"],
        }
    }

    for category in ("gradient", "statuses", "priorities", "tags"):
        palette[category] = {
            key: {"value": value, "text": value, "default": value}
            for key, value in defaults.get(category, {}).items()
        }

    ticket_value = normalize_hex_color(config.colors.ticket_title)
    if ticket_value:
        palette["ticket_title"]["value"] = ticket_value
        palette["ticket_title"]["text"] = ticket_value

    for category_name, source in [
        ("gradient", config.colors.gradient),
        ("statuses", config.colors.statuses),
        ("priorities", config.colors.priorities),
        ("tags", config.colors.tags),
    ]:
        for key, value in source.items():
            key_str = str(key)
            normalized = normalize_hex_color(value)
            if not normalized:
                continue
            category = palette.setdefault(category_name, {})
            entry = category.setdefault(
                key_str,
                {
                    "value": normalized,
                    "text": normalized,
                    "default": defaults.get(category_name, {}).get(
                        key_str, normalized
                    ),
                },
            )
            entry["value"] = normalized
            entry["text"] = normalized
            entry.setdefault(
                "default",
                defaults.get(category_name, {}).get(key_str, normalized),
            )

    return palette


def _color_category_entries(
    config: AppConfig, palette: Dict[str, Dict[str, Dict[str, str]]]
) -> List[Tuple[str, str, List[Dict[str, object]]]]:
    """Return ordered palette entries grouped by section for rendering and parsing."""

    sections: List[Tuple[str, str, List[Dict[str, object]]]] = []

    ticket_entry = palette.get("ticket_title")
    if isinstance(ticket_entry, dict):
        sections.append(
            (
                "ticket_title",
                "Ticket title",
                [
                    {
                        "key": "ticket_title",
                        "label": "Ticket title",
                        "entry": ticket_entry,
                        "field_name": "colors[ticket_title]",
                    }
                ],
            )
        )

    gradient_entries: List[Dict[str, object]] = []
    gradient_palette = palette.get("gradient", {})
    gradient_order = [*GRADIENT_STAGE_ORDER, GRADIENT_OVERDUE_KEY]
    for key in gradient_palette.keys():
        key_str = str(key)
        if key_str not in gradient_order:
            gradient_order.append(key_str)
    stage_indexes = [
        index
        for index in (
            _stage_index_from_key(str(key))
            for key in gradient_order
        )
        if index is not None
    ]
    if stage_indexes:
        stage_count = max(stage_indexes) + 1
    else:
        stage_count = len(GRADIENT_STAGE_ORDER)
    stage_labels = _stage_labels(stage_count)
    for key in gradient_order:
        entry = gradient_palette.get(str(key))
        if not entry:
            continue
        if key == GRADIENT_OVERDUE_KEY:
            label = "Overdue"
        else:
            stage_index = _stage_index_from_key(str(key))
            if stage_index is None:
                label = str(key).replace("_", " ").title()
            else:
                if stage_index >= len(stage_labels):
                    stage_labels = _stage_labels(stage_index + 1)
                label = stage_labels[stage_index]
        gradient_entries.append(
            {
                "key": str(key),
                "label": label,
                "entry": entry,
                "field_name": f"colors[gradient][{key}]",
            }
        )
    if gradient_entries:
        sections.append(("gradient", "Gradient stages", gradient_entries))

    status_entries: List[Dict[str, object]] = []
    status_palette = palette.get("statuses", {})
    status_order = list(DEFAULT_STATUS_COLORS.keys())
    for key in status_palette.keys():
        key_str = str(key)
        if key_str not in status_order:
            status_order.append(key_str)
    for key in status_order:
        entry = status_palette.get(str(key))
        if not entry:
            continue
        label = str(key).replace("_", " ").title()
        status_entries.append(
            {
                "key": str(key),
                "label": label,
                "entry": entry,
                "field_name": f"colors[statuses][{key}]",
            }
        )
    if status_entries:
        sections.append(("statuses", "Status overrides", status_entries))

    priority_entries: List[Dict[str, object]] = []
    priority_palette = palette.get("priorities", {})
    priority_order = list(
        dict.fromkeys([*(str(priority) for priority in config.priorities), *priority_palette.keys()])
    )
    for key in priority_order:
        entry = priority_palette.get(str(key))
        if not entry:
            continue
        priority_entries.append(
            {
                "key": str(key),
                "label": str(key),
                "entry": entry,
                "field_name": f"colors[priorities][{key}]",
            }
        )
    if priority_entries:
        sections.append(("priorities", "Priority colors", priority_entries))

    tag_entries: List[Dict[str, object]] = []
    tag_palette = palette.get("tags", {})
    tag_order = list(DEFAULT_TAG_COLORS.keys())
    for key in tag_palette.keys():
        key_str = str(key)
        if key_str not in tag_order:
            tag_order.append(key_str)
    for key in tag_order:
        entry = tag_palette.get(str(key))
        if not entry:
            continue
        label = str(key).replace("_", " ").title()
        tag_entries.append(
            {
                "key": str(key),
                "label": label,
                "entry": entry,
                "field_name": f"colors[tags][{key}]",
            }
        )
    if tag_entries:
        sections.append(("tags", "Tag colors", tag_entries))

    return sections


def _process_color_entry(
    form_data: Mapping[str, str],
    entry_info: Dict[str, object],
    invalid_labels: List[str],
) -> None:
    """Apply submitted values to a color entry, tracking validation errors."""

    entry = entry_info["entry"]
    if not isinstance(entry, dict):
        return

    default_value = str(entry.get("default", entry.get("value", "")))
    field_name = str(entry_info.get("field_name", ""))
    color_value = str(form_data.get(field_name, "")).strip()

    if not color_value:
        entry["value"] = default_value
        return

    normalized = normalize_hex_color(color_value)
    if normalized is None:
        entry.setdefault("value", default_value)
        label = str(entry_info.get("label", "color"))
        invalid_labels.append(label)
        return

    entry["value"] = normalized


def _color_sections(
    config: AppConfig, palette: Dict[str, Dict[str, Dict[str, str]]]
) -> List[Dict[str, object]]:
    """Return palette metadata for rendering the settings form."""

    sections: List[Dict[str, object]] = []
    for name, label, entries in _color_category_entries(config, palette):
        section_entries: List[Dict[str, object]] = []
        for entry_info in entries:
            entry = entry_info["entry"]
            if not isinstance(entry, dict):
                continue
            section_entries.append(
                {
                    "key": entry_info["key"],
                    "label": entry_info["label"],
                    "value": entry.get("value", entry.get("default")),
                    "default": entry.get("default", entry.get("value")),
                    "field_name": entry_info["field_name"],
                }
            )
        if section_entries:
            sections.append({"name": name, "label": label, "entries": section_entries})
    return sections

def _form_defaults(config: AppConfig) -> Dict[str, object]:
    color_palette = _color_palette_display(config)

    html_sections = (
        list(config.clipboard_summary.html_sections)
        or config.clipboard_summary.sections_for_html()
    )
    text_sections = (
        list(config.clipboard_summary.text_sections)
        or config.clipboard_summary.sections_for_text()
    )

    default_sla = DEFAULT_CONFIG.get("sla", {})
    base_due_stage_days = list(default_sla.get("due_stage_days", []))
    base_priority_stages: Dict[str, List[int]] = {
        str(priority): list(values)
        for priority, values in default_sla.get("priority_stage_days", {}).items()
    }

    due_stage_days = list(config.sla.due_stage_days) or list(base_due_stage_days)

    priority_stage_days: Dict[str, List[int]] = {}
    for priority in config.priorities:
        configured_values = config.sla.priority_stage_days.get(priority)
        if configured_values:
            priority_stage_days[priority] = list(configured_values)
        elif priority in base_priority_stages:
            priority_stage_days[priority] = list(base_priority_stages[priority])
        else:
            priority_stage_days[priority] = list(DEFAULT_PRIORITY_STAGE_DAYS_FALLBACK)

    stage_lengths = [len(due_stage_days)]
    stage_lengths.extend(len(values) for values in priority_stage_days.values())
    stage_lengths.append(len(base_due_stage_days))
    stage_count = max(stage_lengths) if stage_lengths else len(base_due_stage_days) or 1

    padded_due_stage_days = [str(value) for value in due_stage_days]
    if len(padded_due_stage_days) < stage_count:
        padded_due_stage_days.extend([""] * (stage_count - len(padded_due_stage_days)))

    display_priority_stage_days: Dict[str, List[str]] = {}
    for priority, values in priority_stage_days.items():
        display_values = [str(value) for value in values]
        if len(display_values) < stage_count:
            display_values.extend([""] * (stage_count - len(display_values)))
        display_priority_stage_days[priority] = display_values

    default_due_days = config.sla.default_due_days
    default_due_display = "" if default_due_days is None else str(default_due_days)

    return {
        "default_submitted_by": config.default_submitted_by,
        "priorities": "\n".join(config.priorities),
        "hold_reasons": "\n".join(config.hold_reasons),
        "workflow": "\n".join(config.workflow),
        "selected_html_sections": set(html_sections),
        "selected_text_sections": set(text_sections),
        "updates_limit": str(config.clipboard_summary.updates_limit),
        "clipboard_debug_status": config.clipboard_summary.debug_status,
        "auto_return_to_list": config.auto_return_to_list,
        "demo_mode": config.demo_mode,
        "default_due_days": default_due_display,
        "due_stage_days": padded_due_stage_days,
        "priority_stage_days": display_priority_stage_days,
        "sla_stage_count": stage_count,
        "color_palette": color_palette,
    }


@settings_bp.route("/settings", methods=["GET", "POST"])
def view_settings():
    config = _app_config()
    demo_manager = get_demo_manager(current_app)
    compact_mode = _is_compact_mode()
    section_options = _clipboard_section_options(config)

    defaults = _form_defaults(config)
    form_data = deepcopy(defaults)

    if request.method == "POST":
        default_submitted_by = request.form.get("default_submitted_by", "").strip()
        priorities_input = request.form.get("priorities", "")
        hold_reasons_input = request.form.get("hold_reasons", "")
        workflow_input = request.form.get("workflow", "")
        html_section_values = set(request.form.getlist("html_sections"))
        text_section_values = set(request.form.getlist("text_sections"))
        updates_limit_input = request.form.get("updates_limit", "").strip()
        default_due_days_input = request.form.get("default_due_days", "").strip()
        due_stage_day_inputs = [value.strip() for value in request.form.getlist("due_stage_days")]

        debug_status_enabled = request.form.get("clipboard_debug_status") is not None
        auto_return_enabled = request.form.get("auto_return_to_list") is not None
        demo_mode_enabled = request.form.get("demo_mode") is not None

        color_palette = _color_palette_display(config)
        color_entries = _color_category_entries(config, color_palette)
        invalid_color_labels: List[str] = []
        for _, _, entries in color_entries:
            for entry_info in entries:
                _process_color_entry(request.form, entry_info, invalid_color_labels)

        section_names = [name for name, _ in section_options]

        priority_stage_inputs: Dict[str, List[str]] = {}
        prefix = "priority_stage_days["
        for key in request.form.keys():
            if key.startswith(prefix) and key.endswith("]"):
                priority_name = key[len(prefix) : -1]
                priority_stage_inputs[priority_name] = [
                    value.strip() for value in request.form.getlist(key)
                ]

        if not due_stage_day_inputs:
            due_stage_day_inputs = list(defaults.get("due_stage_days", []))

        display_priority_values: Dict[str, List[str]] = {
            priority: list(values)
            for priority, values in defaults.get("priority_stage_days", {}).items()
        }
        for priority, values in priority_stage_inputs.items():
            display_priority_values[priority] = list(values)

        raw_due_stage_values = list(due_stage_day_inputs)
        raw_priority_stage_values = {
            priority: list(values) for priority, values in display_priority_values.items()
        }

        stage_lengths = [len(raw_due_stage_values)]
        stage_lengths.extend(len(values) for values in raw_priority_stage_values.values())
        stage_lengths.append(int(defaults.get("sla_stage_count", 0)))
        stage_count = max(stage_lengths) if stage_lengths else int(defaults.get("sla_stage_count", 0))
        if stage_count <= 0:
            stage_count = max(1, len(raw_due_stage_values))

        due_stage_display = list(raw_due_stage_values)
        if len(due_stage_display) < stage_count:
            due_stage_display.extend([""] * (stage_count - len(due_stage_display)))

        padded_priority_display: Dict[str, List[str]] = {}
        for priority, values in raw_priority_stage_values.items():
            padded = list(values)
            if len(padded) < stage_count:
                padded.extend([""] * (stage_count - len(padded)))
            padded_priority_display[priority] = padded

        form_data = {
            "default_submitted_by": default_submitted_by,
            "priorities": priorities_input,
            "hold_reasons": hold_reasons_input,
            "workflow": workflow_input,
            "selected_html_sections": html_section_values,
            "selected_text_sections": text_section_values,
            "updates_limit": updates_limit_input,
            "clipboard_debug_status": debug_status_enabled,
            "auto_return_to_list": auto_return_enabled,
            "demo_mode": demo_mode_enabled,
            "default_due_days": default_due_days_input,
            "due_stage_days": due_stage_display,
            "priority_stage_days": padded_priority_display,
            "sla_stage_count": stage_count,
            "color_palette": color_palette,
        }

        errors: List[str] = []

        priorities = _parse_multiline_field(priorities_input)
        if not priorities:
            errors.append("Provide at least one priority value.")

        hold_reasons = _parse_multiline_field(hold_reasons_input)
        if not hold_reasons:
            errors.append("Provide at least one hold reason.")

        workflow = _parse_multiline_field(workflow_input)
        if not workflow:
            errors.append("Provide at least one workflow status.")

        html_sections = [
            section for section in section_names if section in html_section_values
        ]
        if not html_sections:
            html_sections = config.clipboard_summary.sections_for_html()

        text_sections = [
            section for section in section_names if section in text_section_values
        ]
        if not text_sections:
            text_sections = html_sections or config.clipboard_summary.sections_for_text()

        if not default_submitted_by:
            errors.append("Default submitter cannot be empty.")

        if updates_limit_input:
            try:
                updates_limit = int(updates_limit_input)
            except ValueError:
                errors.append("Updates limit must be a non-negative integer.")
            else:
                if updates_limit < 0:
                    errors.append("Updates limit must be a non-negative integer.")
        else:
            updates_limit = config.clipboard_summary.updates_limit

        due_stage_days: List[int] = []
        if raw_due_stage_values:
            for value in raw_due_stage_values:
                if not value:
                    continue
                try:
                    number = int(value)
                except ValueError:
                    errors.append("Due stage thresholds must be non-negative integers.")
                    due_stage_days = []
                    break
                if number < 0:
                    errors.append("Due stage thresholds must be non-negative integers.")
                    due_stage_days = []
                    break
                due_stage_days.append(number)

        priority_stage_days: Dict[str, List[int]] = {}
        if raw_priority_stage_values:
            priority_order: List[str] = list(defaults.get("priority_stage_days", {}).keys())
            for priority in raw_priority_stage_values.keys():
                if priority not in priority_order:
                    priority_order.append(priority)

            priority_error_reported = False
            for priority in priority_order:
                raw_values = raw_priority_stage_values.get(priority, [])
                cleaned: List[int] = []
                for value in raw_values:
                    if not value:
                        continue
                    try:
                        number = int(value)
                    except ValueError:
                        if not priority_error_reported:
                            errors.append(
                                "Priority stage thresholds must be non-negative integers."
                            )
                            priority_error_reported = True
                        cleaned = []
                        break
                    if number < 0:
                        if not priority_error_reported:
                            errors.append(
                                "Priority stage thresholds must be non-negative integers."
                            )
                            priority_error_reported = True
                        cleaned = []
                        break
                    cleaned.append(number)
                if cleaned:
                    priority_stage_days[priority] = cleaned

        if default_due_days_input:
            try:
                default_due_days_value = int(default_due_days_input)
            except ValueError:
                errors.append("Default backlog due days must be a non-negative integer.")
                default_due_days_value = config.sla.default_due_days
            else:
                if default_due_days_value < 0:
                    errors.append("Default backlog due days must be a non-negative integer.")
                    default_due_days_value = config.sla.default_due_days
        else:
            default_due_days_value = None

        if invalid_color_labels:
            unique_labels = list(dict.fromkeys(invalid_color_labels))
            errors.append(
                "Provide valid hex colors (example #AABBCC) for: "
                + ", ".join(unique_labels)
                + "."
            )

        should_enable_demo = demo_mode_enabled and not config.demo_mode
        should_disable_demo = not demo_mode_enabled and config.demo_mode

        if errors:
            for message in errors:
                flash(message, "error")
        else:
            gradient_colors: Dict[str, str] = {}
            for key, entry in color_palette.get("gradient", {}).items():
                normalized = normalize_hex_color(entry.get("value")) or normalize_hex_color(
                    entry.get("default")
                )
                if normalized:
                    gradient_colors[str(key)] = normalized

            status_colors: Dict[str, str] = {}
            for key, entry in color_palette.get("statuses", {}).items():
                normalized = normalize_hex_color(entry.get("value")) or normalize_hex_color(
                    entry.get("default")
                )
                if normalized:
                    status_colors[str(key)] = normalized

            priority_colors: Dict[str, str] = {}
            for key, entry in color_palette.get("priorities", {}).items():
                normalized = normalize_hex_color(entry.get("value")) or normalize_hex_color(
                    entry.get("default")
                )
                if normalized:
                    priority_colors[str(key)] = normalized

            tag_colors: Dict[str, str] = {}
            for key, entry in color_palette.get("tags", {}).items():
                normalized = normalize_hex_color(entry.get("value")) or normalize_hex_color(
                    entry.get("default")
                )
                if normalized:
                    tag_colors[str(key)] = normalized

            ticket_title_value = normalize_hex_color(
                color_palette.get("ticket_title", {}).get("value")
            ) or normalize_hex_color(color_palette.get("ticket_title", {}).get("default"))
            if not ticket_title_value:
                ticket_title_value = DEFAULT_TICKET_TITLE_COLOR

            summary = replace(
                config.clipboard_summary,
                html_sections=html_sections,
                text_sections=text_sections,
                updates_limit=updates_limit,
                debug_status=debug_status_enabled,
            )

            updated_sla = replace(
                config.sla,
                due_stage_days=due_stage_days,
                priority_stage_days=priority_stage_days,
                default_due_days=default_due_days_value,
            )

            updated_colors = replace(
                config.colors,
                gradient=gradient_colors,
                statuses=status_colors,
                priorities=priority_colors,
                tags=tag_colors,
                ticket_title=ticket_title_value,
            )

            updated_config = replace(
                config,
                default_submitted_by=default_submitted_by,
                priorities=priorities,
                hold_reasons=hold_reasons,
                workflow=workflow,
                clipboard_summary=summary,
                auto_return_to_list=auto_return_enabled,
                demo_mode=demo_mode_enabled,
                sla=updated_sla,
                colors=updated_colors,
            )

            toggle_error = False
            if should_enable_demo:
                try:
                    demo_manager.enable()
                except DemoModeError as exc:
                    flash(f"Unable to enable demo mode: {exc}", "error")
                    toggle_error = True
            elif should_disable_demo:
                try:
                    demo_manager.disable()
                except DemoModeError as exc:
                    flash(f"Unable to disable demo mode: {exc}", "error")
                    toggle_error = True

            if toggle_error:
                flash("Demo mode change failed; settings were not saved.", "error")
            else:
                if _persist_config(updated_config):
                    flash("Settings updated", "success")
                    redirect_target = (
                        "tickets.list_tickets"
                        if updated_config.auto_return_to_list
                        else "settings.view_settings"
                    )
                    return redirect(
                        url_for(
                            redirect_target,
                            compact=_compact_query_value(compact_mode),
                        )
                    )

                if should_enable_demo:
                    try:
                        demo_manager.disable()
                    except DemoModeError as exc:  # pragma: no cover - log safeguard
                        current_app.logger.warning(
                            "Unable to revert demo mode after save failure: %s", exc
                        )
                elif should_disable_demo:
                    try:
                        demo_manager.enable()
                    except DemoModeError as exc:  # pragma: no cover - log safeguard
                        current_app.logger.warning(
                            "Unable to restore demo mode after save failure: %s", exc
                        )

    demo_status = demo_manager.status()
    color_sections = _color_sections(config, form_data.get("color_palette", {}))

    stage_count_value = form_data.get("sla_stage_count", 0)
    try:
        stage_count = int(stage_count_value)
    except (TypeError, ValueError):
        stage_count = 0
    stage_labels = _stage_labels(stage_count)

    return render_template(
        "settings.html",
        config=config,
        form=form_data,
        demo_status=demo_status,
        compact_mode=compact_mode,
        compact_toggle_url=_build_compact_toggle_url(
            "settings.view_settings", compact_mode
        ),
        clipboard_sections=section_options,
        color_sections=color_sections,
        sla_stage_labels=stage_labels,
    )


@settings_bp.post("/settings/demo-mode")
def toggle_demo_mode():
    config = _app_config()
    demo_manager = get_demo_manager(current_app)
    action = (request.form.get("action") or "").strip().lower()
    compact_mode = _is_compact_mode()

    if action == "enable":
        try:
            demo_manager.enable()
        except DemoModeError as exc:
            flash(f"Unable to enable demo mode: {exc}", "error")
        else:
            if not config.demo_mode:
                updated_config = replace(config, demo_mode=True)
                if _persist_config(updated_config):
                    flash(
                        "Demo mode enabled. Sample data loaded and live data snapshotted.",
                        "success",
                    )
                    config = updated_config
                else:
                    try:
                        demo_manager.disable()
                    except DemoModeError as revert_exc:  # pragma: no cover - safety log
                        current_app.logger.warning(
                            "Unable to revert demo mode after failed persistence: %s",
                            revert_exc,
                        )
            else:
                flash("Demo mode dataset loaded.", "success")
    elif action == "disable":
        try:
            demo_manager.disable()
        except DemoModeError as exc:
            flash(f"Unable to disable demo mode: {exc}", "error")
        else:
            if config.demo_mode:
                updated_config = replace(config, demo_mode=False)
                if _persist_config(updated_config):
                    flash("Demo mode disabled. Original data restored.", "success")
                    config = updated_config
                else:
                    try:
                        demo_manager.enable()
                    except DemoModeError as revert_exc:  # pragma: no cover - safety log
                        current_app.logger.warning(
                            "Unable to re-enable demo mode after save failure: %s",
                            revert_exc,
                        )
            else:
                flash("Demo mode disabled.", "success")
    elif action == "persist":
        if not demo_manager.is_active:
            flash("Enable demo mode before persisting the dataset.", "error")
        else:
            try:
                dataset_path = demo_manager.persist_dataset()
            except DemoModeError as exc:
                flash(f"Unable to persist demo dataset: {exc}", "error")
            else:
                flash(f"Demo dataset saved to {dataset_path}.", "success")
    elif action == "refresh":
        try:
            demo_manager.refresh()
        except DemoModeError as exc:
            flash(f"Unable to refresh demo data: {exc}", "error")
        else:
            flash("Demo data refreshed.", "success")
    else:
        flash("Unrecognized demo mode action.", "error")

    return redirect(
        url_for(
            "settings.view_settings",
            compact=_compact_query_value(compact_mode),
        )
    )
