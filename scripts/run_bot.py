"""Main system bootstrap and automation orchestrator."""

from __future__ import annotations

import argparse
import logging
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import uvicorn
import yaml
from celery import Celery
from fastapi import FastAPI

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai.chat_responder import ChatResponder
from ai.upsell_strategy import UpsellStrategy
from api.routes import router
from api.payment_gateway import PaymentGateway
from automation.add_flow import AddFlow
from automation.snap_sender import SnapSender
from core.account_manager import AccountManager
from core.proxy_manager import ProxyManager
from core.session_manager import SessionManager

stop_event = threading.Event()


def build_celery_app(config: dict[str, Any]) -> Celery:
    """Create configured Celery app."""
    celery_cfg = config.get("celery", {})
    app = Celery("snapchat_bot", broker=celery_cfg.get("broker_url"), backend=celery_cfg.get("result_backend"))
    app.conf.task_default_queue = "snapchat_bot"
    return app


def start_celery_worker() -> subprocess.Popen[str] | None:
    """Start Celery worker process for background scheduling."""
    try:
        return subprocess.Popen(
            ["celery", "-A", "scripts.run_bot:celery_app", "worker", "--loglevel=INFO"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except Exception as exc:
        logging.getLogger(__name__).warning("Celery worker not started: %s", exc)
        return None


def automation_loop(
    account_manager: AccountManager,
    session_manager: SessionManager,
    proxy_manager: ProxyManager,
    add_flow: AddFlow,
    snap_sender: SnapSender,
    chat_responder: ChatResponder,
    upsell_strategy: UpsellStrategy,
    dry_run: bool,
) -> None:
    """Main orchestration loop for accounts."""
    logger = logging.getLogger("automation_loop")
    while not stop_event.is_set():
        accounts = account_manager.list_active_accounts()
        for account in accounts:
            if stop_event.is_set():
                break
            username = account["username"]
            try:
                if not account.get("assigned_proxy"):
                    proxy = proxy_manager.get_proxy(username)
                    if proxy:
                        account_manager.assign_proxy(username, proxy)

                if not session_manager.check_session_health(account):
                    session_manager.create_session(account)
                    account_manager.update_session_status(username, "running")

                # add-flow task
                add_flow.add_friend(account, f"target_{int(time.time()) % 1000}")

                # snap task (dry-run uses placeholder media)
                media_path = "README.md" if dry_run else "README.md"
                snap_sender.send_snap(account, "sample_recipient", media_path, caption="Daily update")

                # chat/upsell task
                context = {"product": "premium_snap_pack"}
                convo = ["hey", "I am interested in premium"]
                response = chat_responder.generate_response(convo, context)
                if upsell_strategy.should_upsell(convo):
                    upsell_strategy.get_upsell_message({"tone": "friendly"}, "premium_snap_pack")
                logger.info("AI response for %s: %s", username, response)
            except Exception as exc:
                logger.exception("Automation failure for %s: %s", username, exc)
                account_manager.increment_error_count(username)
                session_manager.recover_session(account)
        stop_event.wait(10)


def build_api_app() -> FastAPI:
    """Create API app and register routes."""
    app = FastAPI(title="Snapchat Bot Automation API")
    app.include_router(router)
    return app


def parse_args() -> argparse.Namespace:
    """Parse runtime CLI flags."""
    parser = argparse.ArgumentParser(description="Run Snapchat bot automation system")
    parser.add_argument("--config", default="config/settings.yaml", help="Path to settings YAML")
    parser.add_argument("--accounts", nargs="*", default=[], help="Specific usernames to run")
    parser.add_argument("--dry-run", action="store_true", help="Run without real Appium interactions")
    parser.add_argument("--host", default="127.0.0.1", help="FastAPI bind host")
    parser.add_argument("--port", type=int, default=8000, help="FastAPI bind port")
    return parser.parse_args()


def install_signal_handlers(session_manager: SessionManager, account_manager: AccountManager) -> None:
    """Install SIGINT/SIGTERM handlers for graceful shutdown."""

    def _handler(signum: int, _frame: Any) -> None:
        logging.getLogger(__name__).info("Received signal %s, shutting down", signum)
        stop_event.set()
        for account in account_manager.list_active_accounts():
            session_manager.destroy_session(account)
            account_manager.update_session_status(account["username"], "stopped")

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)


if __name__ == "__main__":
    args = parse_args()

    with open(args.config, "r", encoding="utf-8") as handle:
        cfg = yaml.safe_load(handle) or {}

    logging.basicConfig(level=getattr(logging, cfg.get("logging", {}).get("level", "INFO"), logging.INFO))

    account_manager = AccountManager(config_path=args.config)
    session_manager = SessionManager(config_path=args.config, dry_run=args.dry_run)
    proxy_manager = ProxyManager(settings_path=args.config)
    payment_gateway = PaymentGateway(config_path=args.config)
    add_flow = AddFlow(session_manager=session_manager, account_manager=account_manager, config_path=args.config)
    snap_sender = SnapSender(session_manager=session_manager, payment_gateway=payment_gateway, config_path=args.config)
    chat_responder = ChatResponder(config_path=args.config)
    upsell_strategy = UpsellStrategy()

    if args.accounts:
        existing = {a["username"] for a in account_manager.list_active_accounts()}
        for username in args.accounts:
            if username not in existing:
                account_manager.add_account(username, "placeholder_password", {"udid": f"emulator-{abs(hash(username)) % 10000:04d}"})

    celery_app = build_celery_app(cfg)
    worker = start_celery_worker() if not args.dry_run else None

    install_signal_handlers(session_manager, account_manager)

    loop_thread = threading.Thread(
        target=automation_loop,
        args=(account_manager, session_manager, proxy_manager, add_flow, snap_sender, chat_responder, upsell_strategy, args.dry_run),
        daemon=True,
    )
    loop_thread.start()

    app = build_api_app()
    uvicorn.run(app, host=args.host, port=args.port)

    stop_event.set()
    loop_thread.join(timeout=5)
    if worker:
        worker.terminate()
