"""Flask application factory for TicketTracker."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from flask import Flask

from .config import AppConfig, load_config
from .extensions import db


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

    app.config["SQLALCHEMY_DATABASE_URI"] = app_config.database_uri
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["UPLOAD_FOLDER"] = str(app_config.uploads_path)
    app.config["APP_CONFIG"] = app_config

    # Ensure the uploads directory exists before the first request.
    uploads_path = app_config.uploads_path
    uploads_path.mkdir(parents=True, exist_ok=True)

    db.init_app(app)

    with app.app_context():
        # Import models so SQLAlchemy registers them, then create tables if needed.
        from . import models  # noqa: F401

        db.create_all()

    from .views.tickets import tickets_bp

    app.register_blueprint(tickets_bp)

    @app.context_processor
    def inject_app_config() -> dict[str, AppConfig]:
        return {"app_config": app_config}

    return app


if __name__ == "__main__":
    application = create_app()
    application.run(debug=True)
