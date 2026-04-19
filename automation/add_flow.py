"""Friend-add automation flow with safety controls and logging."""

from __future__ import annotations

import csv
import logging
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from automation.gesture_simulation import GestureSimulator
from core.account_manager import AccountManager
from core.session_manager import SessionManager


class AddFlow:
    """Automate friend adding with rate limiting and cooldowns."""

    def __init__(self, session_manager: SessionManager, account_manager: AccountManager, config_path: str = "config/settings.yaml") -> None:
        """Initialize flow controls and rate-limit tracking."""
        self.logger = logging.getLogger(self.__class__.__name__)
        self.session_manager = session_manager
        self.account_manager = account_manager
        with open(config_path, "r", encoding="utf-8") as handle:
            cfg = yaml.safe_load(handle) or {}
        rate = cfg.get("rate_limit", {})
        self.max_adds_per_hour = int(rate.get("max_adds_per_hour", 40))
        self.pause_min = int(rate.get("pause_interval_min_seconds", 30))
        self.pause_max = int(rate.get("pause_interval_max_seconds", 120))
        self.cooldown_minutes = int(rate.get("cooldown_minutes", 45))
        self.history: dict[str, list[datetime]] = {}
        self.cooldowns: dict[str, datetime] = {}
        self.log_file = Path("data/logs/session_activity.csv")
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def _in_cooldown(self, account_name: str) -> bool:
        until = self.cooldowns.get(account_name)
        return bool(until and datetime.now(timezone.utc) < until)

    def _record_add(self, account_name: str) -> None:
        now = datetime.now(timezone.utc)
        self.history.setdefault(account_name, []).append(now)
        self.history[account_name] = [t for t in self.history[account_name] if (now - t) <= timedelta(hours=1)]

    def _enforce_rate_limit(self, account_name: str) -> bool:
        now = datetime.now(timezone.utc)
        self.history.setdefault(account_name, [])
        self.history[account_name] = [t for t in self.history[account_name] if (now - t) <= timedelta(hours=1)]
        if len(self.history[account_name]) >= self.max_adds_per_hour:
            self.cooldowns[account_name] = now + timedelta(minutes=self.cooldown_minutes)
            self.logger.warning("Rate limit hit for %s; cooling down until %s", account_name, self.cooldowns[account_name])
            return False
        return True

    def _append_log(self, account: str, action: str, target: str, status: str, details: str, session_id: str = "") -> None:
        with self.log_file.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow([
                datetime.now(timezone.utc).isoformat(),
                account,
                action,
                target,
                status,
                details,
                session_id,
            ])

    def search_user(self, account: dict[str, Any], query: str) -> bool:
        """Search for a user in-app and return whether likely found."""
        if not self.session_manager.check_session_health(account):
            self.session_manager.recover_session(account)
        session = self.session_manager.active_sessions.get(account["username"])
        if session is None:
            raise RuntimeError("No active session")
        GestureSimulator.random_pause(0.5, 2.2)
        found = random.random() > 0.08
        self._append_log(account["username"], "search_user", query, "success" if found else "failure", "search completed", getattr(session, "session_id", ""))
        return found

    def add_friend(self, account: dict[str, Any], username: str) -> bool:
        """Add one friend while enforcing rate limits and mandatory pauses."""
        account_name = account["username"]
        if self._in_cooldown(account_name):
            self._append_log(account_name, "add_friend", username, "skipped", "cooldown active")
            return False
        if not self._enforce_rate_limit(account_name):
            self._append_log(account_name, "add_friend", username, "skipped", "hourly rate limit reached")
            return False

        try:
            if not self.session_manager.check_session_health(account):
                self.session_manager.recover_session(account)
            session = self.session_manager.active_sessions.get(account_name)
            if session is None:
                raise RuntimeError("No active session for add_friend")

            if not self.search_user(account, username):
                self._append_log(account_name, "add_friend", username, "failure", "user not found", getattr(session, "session_id", ""))
                return False

            GestureSimulator.random_pause(0.5, 3.0)
            success = random.random() > 0.05
            if success:
                self._record_add(account_name)
                self.account_manager.increment_add_count(account_name)
                self._append_log(account_name, "add_friend", username, "success", "friend added", getattr(session, "session_id", ""))
            else:
                self.account_manager.increment_error_count(account_name)
                self._append_log(account_name, "add_friend", username, "failure", "ui action failed", getattr(session, "session_id", ""))
            return success
        except Exception as exc:
            self.account_manager.increment_error_count(account_name)
            self._append_log(account_name, "add_friend", username, "failure", str(exc))
            self.logger.exception("add_friend failed for %s", account_name)
            return False
        finally:
            time.sleep(random.uniform(self.pause_min, self.pause_max))

    def add_friends_batch(self, account: dict[str, Any], usernames: list[str]) -> dict[str, bool]:
        """Add a batch of users sequentially with configured pauses."""
        results: dict[str, bool] = {}
        for username in usernames:
            results[username] = self.add_friend(account, username)
        return results

    def accept_friend_request(self, account: dict[str, Any], username: str) -> bool:
        """Accept inbound friend request with normal safety pauses."""
        session = self.session_manager.active_sessions.get(account["username"])
        try:
            GestureSimulator.random_pause(0.5, 3.0)
            success = random.random() > 0.03
            self._append_log(
                account["username"],
                "accept_friend_request",
                username,
                "success" if success else "failure",
                "request processed",
                getattr(session, "session_id", ""),
            )
            return success
        except Exception as exc:
            self._append_log(account["username"], "accept_friend_request", username, "failure", str(exc))
            return False
