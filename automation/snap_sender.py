"""Snap send pipeline with payment and retry logic."""

from __future__ import annotations

import logging
import random
import re
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from api.payment_gateway import PaymentGateway
from automation.gesture_simulation import GestureSimulator
from core.session_manager import SessionManager


class SnapSender:
    """Send snaps reliably with session checks, retries, and payment link support."""

    def __init__(self, session_manager: SessionManager, payment_gateway: PaymentGateway, config_path: str = "config/settings.yaml") -> None:
        """Initialize sender controls and retry settings."""
        self.logger = logging.getLogger(self.__class__.__name__)
        self.session_manager = session_manager
        self.payment_gateway = payment_gateway
        with open(config_path, "r", encoding="utf-8") as handle:
            cfg = yaml.safe_load(handle) or {}
        self.max_retries = int(cfg.get("rate_limit", {}).get("snap_max_retries", 3))
        self.media_root = Path(cfg.get("media", {}).get("root_path", "data/media")).resolve()
        self.media_root.mkdir(parents=True, exist_ok=True)
        self.allowed_media_pattern = re.compile(r"^[A-Za-z0-9_.-]+$")
        self.simulated_failure_rate = float(cfg.get("automation", {}).get("snap_failure_rate", 0.08))
        self.delivery_status: dict[str, dict[str, Any]] = {}

    def _ensure_media(self, media_path: str) -> Path:
        if not self.allowed_media_pattern.fullmatch(media_path):
            raise ValueError("Invalid media identifier")
        inventory = {item.name: item for item in self.media_root.iterdir() if item.is_file()}
        resolved = inventory.get(media_path)
        if not resolved:
            raise FileNotFoundError(f"Media file not found in media root: {media_path}")
        return resolved.resolve()

    def send_snap(
        self,
        account: dict[str, Any],
        recipient: str,
        media_path: str,
        caption: str | None = None,
        link: str | None = None,
    ) -> dict[str, Any]:
        """Send one snap with retries and optional link embedding."""
        resolved_media_path = self._ensure_media(media_path)
        final_caption = caption or ""
        if link:
            final_caption = f"{final_caption} {link}".strip()

        if not self.session_manager.check_session_health(account):
            self.session_manager.recover_session(account)
        session = self.session_manager.active_sessions.get(account["username"])
        if session is None:
            raise RuntimeError("No active session for send_snap")

        for attempt in range(1, self.max_retries + 1):
            try:
                GestureSimulator.random_pause(0.5, 3.0)
                snap_id = f"snap_{uuid4().hex[:12]}"
                success = random.random() > self.simulated_failure_rate
                status = "sent" if success else "failed"
                payload = {
                    "snap_id": snap_id,
                    "account": account["username"],
                    "recipient": recipient,
                    "media_path": str(resolved_media_path),
                    "caption": final_caption,
                    "status": status,
                    "session_id": getattr(session, "session_id", ""),
                    "attempt": attempt,
                }
                self.delivery_status[snap_id] = payload
                if success:
                    return payload
                time.sleep(2 ** attempt)
            except Exception as exc:
                self.logger.warning("Snap send failed for %s (attempt %s): %s", recipient, attempt, exc)
                time.sleep(2 ** attempt)

        failed_id = f"snap_{uuid4().hex[:12]}"
        payload = {
            "snap_id": failed_id,
            "account": account["username"],
            "recipient": recipient,
            "media_path": str(resolved_media_path),
            "caption": final_caption,
            "status": "failed",
            "session_id": getattr(session, "session_id", ""),
            "attempt": self.max_retries,
        }
        self.delivery_status[failed_id] = payload
        return payload

    def send_snap_batch(self, account: dict[str, Any], recipients: list[str], media_path: str) -> list[dict[str, Any]]:
        """Send same media to a batch of recipients."""
        return [self.send_snap(account, recipient, media_path) for recipient in recipients]

    def send_snap_with_payment_link(self, account: dict[str, Any], recipient: str, media_path: str, payment_url: str) -> dict[str, Any]:
        """Send monetized snap with payment link embed."""
        return self.send_snap(account, recipient, media_path, caption="Unlock premium content:", link=payment_url)

    def send_after_payment(
        self,
        account: dict[str, Any],
        recipient: str,
        media_path: str,
        payment_id: str,
        caption: str | None = None,
    ) -> dict[str, Any]:
        """Deliver content only after payment confirmation."""
        status = self.payment_gateway.check_payment_status(payment_id)
        if status not in {"paid", "succeeded"}:
            return {"status": "blocked", "reason": f"payment status is {status}", "payment_id": payment_id}
        return self.send_snap(account, recipient, media_path, caption=caption)

    def check_delivery_status(self, account: dict[str, Any], snap_id: str) -> dict[str, Any]:
        """Get current delivery status for a snap."""
        status = self.delivery_status.get(snap_id)
        if status:
            return status
        return {"snap_id": snap_id, "account": account["username"], "status": "unknown"}
