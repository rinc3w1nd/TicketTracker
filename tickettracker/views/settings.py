"""Application settings management views."""
from __future__ import annotations

from dataclasses import replace
from typing import Dict, List

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from ..config import AppConfig, save_config
from ..demo import DemoModeError, get_demo_manager


settings_bp = Blueprint("settings", __name__)


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


def _form_defaults(config: AppConfig) -> Dict[str, object]:
    html_sections = (
        list(config.clipboard_summary.html_sections)
        or config.clipboard_summary.sections_for_html()
    )
    text_sections = (
        list(config.clipboard_summary.text_sections)
        or config.clipboard_summary.sections_for_text()
    )

    return {
        "default_submitted_by": config.default_submitted_by,
        "priorities": "\n".join(config.priorities),
        "hold_reasons": "\n".join(config.hold_reasons),
        "workflow": "\n".join(config.workflow),
        "html_sections": "\n".join(html_sections),
        "text_sections": "\n".join(text_sections),
        "updates_limit": str(config.clipboard_summary.updates_limit),
        "demo_mode": config.demo_mode,
    }


@settings_bp.route("/settings", methods=["GET", "POST"])
def view_settings():
    config = _app_config()
    demo_manager = get_demo_manager(current_app)
    compact_mode = _is_compact_mode()

    form_data = _form_defaults(config)

    if request.method == "POST":
        default_submitted_by = request.form.get("default_submitted_by", "").strip()
        priorities_input = request.form.get("priorities", "")
        hold_reasons_input = request.form.get("hold_reasons", "")
        workflow_input = request.form.get("workflow", "")
        html_sections_input = request.form.get("html_sections", "")
        text_sections_input = request.form.get("text_sections", "")
        updates_limit_input = request.form.get("updates_limit", "").strip()
        demo_mode_enabled = request.form.get("demo_mode") is not None

        form_data = {
            "default_submitted_by": default_submitted_by,
            "priorities": priorities_input,
            "hold_reasons": hold_reasons_input,
            "workflow": workflow_input,
            "html_sections": html_sections_input,
            "text_sections": text_sections_input,
            "updates_limit": updates_limit_input,
            "demo_mode": demo_mode_enabled,
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

        html_sections = _parse_multiline_field(html_sections_input)
        if not html_sections:
            html_sections = config.clipboard_summary.sections_for_html()

        text_sections = _parse_multiline_field(text_sections_input)
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

        should_enable_demo = demo_mode_enabled and not config.demo_mode
        should_disable_demo = not demo_mode_enabled and config.demo_mode

        if errors:
            for message in errors:
                flash(message, "error")
        else:
            summary = replace(
                config.clipboard_summary,
                html_sections=html_sections,
                text_sections=text_sections,
                updates_limit=updates_limit,
            )

            updated_config = replace(
                config,
                default_submitted_by=default_submitted_by,
                priorities=priorities,
                hold_reasons=hold_reasons,
                workflow=workflow,
                clipboard_summary=summary,
                demo_mode=demo_mode_enabled,
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
                    return redirect(
                        url_for(
                            "settings.view_settings",
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

    return render_template(
        "settings.html",
        config=config,
        form=form_data,
        demo_status=demo_status,
        compact_mode=compact_mode,
        compact_toggle_url=_build_compact_toggle_url(
            "settings.view_settings", compact_mode
        ),
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
