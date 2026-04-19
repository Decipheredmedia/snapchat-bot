"""FastAPI routes for bot operations and observability."""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ai.chat_responder import ChatResponder
from ai.upsell_strategy import UpsellStrategy
from api.auth import require_api_key
from api.payment_gateway import PaymentGateway
from automation.add_flow import AddFlow
from automation.snap_sender import SnapSender
from core.account_manager import AccountManager
from core.proxy_manager import ProxyManager
from core.session_manager import SessionManager

logger = logging.getLogger(__name__)
router = APIRouter()

account_manager = AccountManager()
proxy_manager = ProxyManager()
session_manager = SessionManager(dry_run=True)
payment_gateway = PaymentGateway()
add_flow = AddFlow(session_manager=session_manager, account_manager=account_manager)
snap_sender = SnapSender(session_manager=session_manager, payment_gateway=payment_gateway)
chat_responder = ChatResponder()
upsell_strategy = UpsellStrategy()


class AccountCreateRequest(BaseModel):
    username: str
    password: str
    device_fingerprint: dict[str, Any] = Field(default_factory=dict)


class SnapSendRequest(BaseModel):
    account: str
    recipient: str
    media_path: str
    caption: str | None = None
    link: str | None = None


class FriendAddRequest(BaseModel):
    account: str
    username: str


@router.post("/accounts")
def add_account(payload: AccountCreateRequest, _: str = Depends(require_api_key)) -> dict[str, Any]:
    """Add or update an account and assign a proxy."""
    account = account_manager.add_account(payload.username, payload.password, payload.device_fingerprint)
    proxy = proxy_manager.get_proxy(payload.username)
    if proxy:
        account_manager.assign_proxy(payload.username, proxy)
        account["assigned_proxy"] = proxy
    return account


@router.get("/accounts")
def list_accounts(_: str = Depends(require_api_key)) -> list[dict[str, Any]]:
    """List active accounts."""
    return account_manager.list_active_accounts()


@router.get("/accounts/{username}")
def get_account(username: str, _: str = Depends(require_api_key)) -> dict[str, Any]:
    """Get account details and health."""
    account = account_manager.get_account(username)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    health = account_manager.get_health_status(username)
    return {"account": account, "health": health}


@router.post("/accounts/{username}/start")
def start_account(username: str, _: str = Depends(require_api_key)) -> dict[str, Any]:
    """Start automation session for account."""
    account = account_manager.get_account(username)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    session = session_manager.create_session(account)
    account_manager.update_session_status(username, "running")
    return {"status": "started", "session_id": getattr(session, "session_id", "")}


@router.post("/accounts/{username}/stop")
def stop_account(username: str, _: str = Depends(require_api_key)) -> dict[str, Any]:
    """Stop automation session for account."""
    account = account_manager.get_account(username)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    session_manager.destroy_session(account)
    account_manager.update_session_status(username, "stopped")
    return {"status": "stopped"}


@router.post("/snaps/send")
def send_snap(payload: SnapSendRequest, _: str = Depends(require_api_key)) -> dict[str, Any]:
    """Trigger snap send pipeline."""
    account = account_manager.get_account(payload.account)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return snap_sender.send_snap(account, payload.recipient, payload.media_path, caption=payload.caption, link=payload.link)


@router.post("/friends/add")
def add_friend(payload: FriendAddRequest, _: str = Depends(require_api_key)) -> dict[str, Any]:
    """Trigger friend add flow."""
    account = account_manager.get_account(payload.account)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    success = add_flow.add_friend(account, payload.username)
    return {"success": success}


@router.get("/logs")
def get_logs(_: str = Depends(require_api_key), limit: int = 100) -> list[dict[str, Any]]:
    """Return recent activity logs."""
    log_path = Path("data/logs/session_activity.csv")
    if not log_path.exists():
        return []
    with log_path.open("r", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return rows[-limit:]


@router.get("/stats")
def get_stats(_: str = Depends(require_api_key)) -> dict[str, Any]:
    """Return high-level automation performance stats."""
    accounts = account_manager.list_active_accounts()
    sent = sum(1 for s in snap_sender.delivery_status.values() if s.get("status") == "sent")
    failed = sum(1 for s in snap_sender.delivery_status.values() if s.get("status") == "failed")
    return {
        "active_accounts": len(accounts),
        "active_sessions": session_manager.get_active_sessions(),
        "proxy_stats": proxy_manager.get_proxy_stats(),
        "snap_sent": sent,
        "snap_failed": failed,
        "upsell": upsell_strategy.get_upsell_stats(),
    }


@router.get("/health")
def health() -> dict[str, Any]:
    """System health check endpoint."""
    return {"status": "ok", "service": "snapchat-bot-automation"}
