"""Command-line helpers for TicketTracker administration."""
from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from typing import Sequence

from flask import current_app

from .app import create_app
from .config import AppConfig, save_config
from .demo import DemoModeError, get_demo_manager


def _persist_demo_flag(value: bool) -> AppConfig:
    config: AppConfig = current_app.config["APP_CONFIG"]
    if config.demo_mode == value:
        return config

    updated_config = replace(config, demo_mode=value)
    try:
        save_config(updated_config)
    except ValueError as exc:
        raise DemoModeError(
            "Unable to persist configuration changes for demo mode."
        ) from exc

    current_app.config["APP_CONFIG"] = updated_config
    current_app.config["DEMO_MODE"] = updated_config.demo_mode
    return updated_config


def _handle_demo_action(action: str) -> int:
    manager = get_demo_manager(current_app)
    config: AppConfig = current_app.config["APP_CONFIG"]

    if action == "enable":
        try:
            manager.enable()
        except DemoModeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        try:
            config = _persist_demo_flag(True)
        except DemoModeError as exc:
            try:
                manager.disable()
            except DemoModeError:
                pass
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        message = "Demo mode enabled. Sample dataset loaded and live data snapshotted."
    elif action == "disable":
        try:
            manager.disable()
        except DemoModeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        try:
            config = _persist_demo_flag(False)
        except DemoModeError as exc:
            try:
                manager.enable()
            except DemoModeError:
                pass
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        message = "Demo mode disabled. Original data restored."
    elif action == "refresh":
        try:
            manager.refresh()
        except DemoModeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        message = "Demo dataset refreshed."
    else:
        print(f"Unknown demo action: {action}", file=sys.stderr)
        return 1

    current_app.config["APP_CONFIG"] = config
    print(message)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tickettracker", description="TicketTracker utilities")
    subparsers = parser.add_subparsers(dest="command")

    demo_parser = subparsers.add_parser(
        "demo", help="Manage demo mode and sample dataset"
    )
    demo_parser.add_argument(
        "action", choices=("enable", "disable", "refresh"), help="Demo mode action to perform"
    )
    demo_parser.add_argument(
        "--config",
        dest="config_path",
        help="Path to configuration file (defaults to standard lookup)",
    )

    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command == "demo":
        app = create_app(args.config_path)
        with app.app_context():
            return _handle_demo_action(args.action)

    parser.print_help()
    return 1


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
