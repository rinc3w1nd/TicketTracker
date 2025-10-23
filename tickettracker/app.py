"""Flask application factory for TicketTracker."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from flask import Flask, current_app
from markupsafe import Markup, escape

from .config import AppConfig, load_config
from .demo import DemoModeError, get_demo_manager
from .extensions import db
from .migrations import run_migrations


def linebreaks(value: str | Markup | None) -> Markup:
    """Convert newlines to ``<br />`` tags while keeping content safe."""

    if value is None:
        return Markup("")

    br = Markup("<br />")

    if isinstance(value, Markup):
        normalized_markup = value.replace("\r\n", "\n").replace("\r", "\n")
        return normalized_markup.replace("\n", br)

    text = str(value)
    normalized_text = text.replace("\r\n", "\n").replace("\r", "\n")
    escaped_text = escape(normalized_text)
    return escaped_text.replace("\n", br)


def create_app(config_path: Optional[str | Path] = None) -> Flask:
    """Create and configure the Flask application."""

    repo_root = Path(__file__).resolve().parent.parent
    app = Flask(
        __name__,
        instance_relative_config=True,
        template_folder=str(repo_root / "templates"),
        static_folder=str(repo_root / "static"),
    )
    app_config: AppConfig = load_config(config_path)

    app.config["SECRET_KEY"] = app_config.secret_key

    app.config["SQLALCHEMY_DATABASE_URI"] = app_config.database_uri
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["UPLOAD_FOLDER"] = str(app_config.uploads_path)
    app.config["APP_CONFIG"] = app_config
    app.config["DEMO_MODE"] = app_config.demo_mode

    # Ensure the uploads directory exists before the first request.
    uploads_path = app_config.uploads_path
    uploads_path.mkdir(parents=True, exist_ok=True)

    db.init_app(app)

    with app.app_context():
        # Import models so SQLAlchemy registers them, then create tables if needed.
        from . import models  # noqa: F401

        db.create_all()
        run_migrations()

        demo_manager = get_demo_manager(app)
        if app_config.demo_mode:
            try:
                demo_manager.enable()
            except DemoModeError as exc:
                app.logger.warning("Unable to enable demo mode during startup: %s", exc)
        elif demo_manager.is_active:
            try:
                demo_manager.disable()
            except DemoModeError as exc:  # pragma: no cover - defensive logging
                app.logger.warning("Unable to restore data when disabling demo mode: %s", exc)

    from .views.settings import settings_bp
    from .views.tickets import tickets_bp

    app.register_blueprint(settings_bp)
    app.register_blueprint(tickets_bp)
    app.add_template_filter(linebreaks, name="linebreaks")

    @app.context_processor
    def inject_app_config() -> dict[str, AppConfig]:
        return {"app_config": current_app.config["APP_CONFIG"]}

    return app


if __name__ == "__main__":
    application = create_app()
    application.run(debug=True)
