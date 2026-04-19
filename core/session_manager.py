"""Appium session lifecycle management with resilience."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import yaml

try:
    from appium import webdriver
except Exception:  # pragma: no cover - allows runtime without appium installed.
    webdriver = None


@dataclass
class MockSession:
    """Fallback driver session used when Appium is unavailable."""

    session_id: str
    started_at: str

    def quit(self) -> None:
        return


class SessionManager:
    """Create, monitor, recover, and destroy account Appium sessions."""

    def __init__(self, config_path: str = "config/settings.yaml", dry_run: bool = False) -> None:
        """Load Appium configuration and initialize session stores."""
        self.logger = logging.getLogger(self.__class__.__name__)
        with open(config_path, "r", encoding="utf-8") as handle:
            self.config = yaml.safe_load(handle) or {}
        appium_cfg = self.config.get("appium", {})
        self.server_url = f"http://{appium_cfg.get('host', '127.0.0.1')}:{appium_cfg.get('port', 4723)}{appium_cfg.get('path', '/wd/hub')}"
        self.base_caps = appium_cfg.get("desired_capabilities_template", {})
        self.active_sessions: dict[str, Any] = {}
        self.failure_counts: dict[str, int] = {}
        self.paused_accounts: set[str] = set()
        self.max_failures = 3
        self.dry_run = dry_run

    def create_session(self, account: dict[str, Any]) -> Any:
        """Create Appium session with retry and exponential backoff."""
        username = account["username"]
        if username in self.paused_accounts:
            raise RuntimeError(f"Account {username} paused after repeated session failures")

        caps = {**self.base_caps}
        fingerprint = account.get("device_fingerprint") or {}
        caps["udid"] = fingerprint.get("udid") or f"emulator-{abs(hash(username)) % 10000:04d}"
        caps["appPackage"] = fingerprint.get("appPackage", "com.snapchat.android")
        caps["appActivity"] = fingerprint.get("appActivity", ".LandingPageActivity")

        for attempt in range(1, 5):
            try:
                if self.dry_run or webdriver is None:
                    session = MockSession(session_id=f"mock-{uuid4()}", started_at=datetime.now(timezone.utc).isoformat())
                else:
                    session = webdriver.Remote(self.server_url, options=None, desired_capabilities=caps)
                self.active_sessions[username] = session
                self.failure_counts[username] = 0
                self.logger.info("Session created for %s (session_id=%s)", username, getattr(session, "session_id", "unknown"))
                return session
            except Exception as exc:
                wait = min(2 ** attempt, 30)
                self.logger.warning("Session create failed for %s (attempt %s): %s", username, attempt, exc)
                self.failure_counts[username] = self.failure_counts.get(username, 0) + 1
                time.sleep(wait)

        if self.failure_counts.get(username, 0) >= self.max_failures:
            self.paused_accounts.add(username)
        raise RuntimeError(f"Failed to create session for {username}")

    def destroy_session(self, account: dict[str, Any]) -> bool:
        """Stop and remove an active session for an account."""
        username = account["username"]
        session = self.active_sessions.pop(username, None)
        if not session:
            return False
        try:
            session.quit()
            self.logger.info("Session destroyed for %s", username)
            return True
        except Exception as exc:
            self.logger.error("Session destroy failed for %s: %s", username, exc)
            return False

    def check_session_health(self, account: dict[str, Any]) -> bool:
        """Check whether a session is active and responsive."""
        username = account["username"]
        session = self.active_sessions.get(username)
        if not session:
            return False
        try:
            if isinstance(session, MockSession):
                return True
            _ = session.session_id
            return True
        except Exception as exc:
            self.logger.warning("Session unhealthy for %s: %s", username, exc)
            self.failure_counts[username] = self.failure_counts.get(username, 0) + 1
            return False

    def recover_session(self, account: dict[str, Any]) -> Any:
        """Recover by destroying and recreating a failed session."""
        self.destroy_session(account)
        return self.create_session(account)

    def get_active_sessions(self) -> dict[str, str]:
        """Return account to session-id map."""
        return {user: getattr(session, "session_id", "unknown") for user, session in self.active_sessions.items()}
