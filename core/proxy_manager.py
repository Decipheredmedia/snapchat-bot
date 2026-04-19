"""Proxy assignment and rotation with account isolation."""

from __future__ import annotations

import logging
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


class ProxyManager:
    """Manage rotating proxies with per-account isolation and health checks."""

    def __init__(self, proxy_config_path: str = "config/proxy_list.yaml", settings_path: str = "config/settings.yaml") -> None:
        """Load proxy inventory and runtime settings."""
        self.logger = logging.getLogger(self.__class__.__name__)
        self.proxy_config_path = proxy_config_path
        self.settings_path = settings_path
        self.proxies = self._load_proxies(proxy_config_path)
        self.settings = self._load_settings(settings_path)
        self.account_assignments: dict[str, dict[str, Any]] = {}
        self.proxy_stats: dict[str, dict[str, Any]] = {
            self._key(proxy): {"healthy": True, "assigned": None, "uses": 0, "failures": 0, "last_checked": None}
            for proxy in self.proxies
        }

    @staticmethod
    def _load_proxies(path: str) -> list[dict[str, Any]]:
        with open(path, "r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
        return payload.get("proxies", [])

    @staticmethod
    def _load_settings(path: str) -> dict[str, Any]:
        with open(path, "r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}

    @staticmethod
    def _key(proxy: dict[str, Any]) -> str:
        return f"{proxy.get('host')}:{proxy.get('port')}"

    def get_proxy(self, account: str) -> dict[str, Any] | None:
        """Get or allocate an isolated healthy proxy for an account."""
        if account in self.account_assignments:
            return self.account_assignments[account]

        for proxy in self.proxies:
            key = self._key(proxy)
            stats = self.proxy_stats[key]
            if stats["assigned"] is None and stats["healthy"] and self.validate_proxy(proxy):
                stats["assigned"] = account
                stats["uses"] += 1
                self.account_assignments[account] = proxy
                self.logger.info("Assigned proxy %s to %s", key, account)
                return proxy

        self.logger.warning("No healthy proxy available for %s", account)
        return None

    def rotate_proxy(self, account: str) -> dict[str, Any] | None:
        """Rotate to next available healthy proxy for the account."""
        current = self.account_assignments.get(account)
        if current:
            current_key = self._key(current)
            self.proxy_stats[current_key]["assigned"] = None

        if account in self.account_assignments:
            del self.account_assignments[account]

        for proxy in self.proxies:
            key = self._key(proxy)
            stats = self.proxy_stats[key]
            if stats["assigned"] is None and stats["healthy"] and self.validate_proxy(proxy):
                stats["assigned"] = account
                stats["uses"] += 1
                self.account_assignments[account] = proxy
                self.logger.info("Rotated proxy for %s -> %s", account, key)
                return proxy

        self.logger.error("Proxy rotation failed for %s", account)
        return None

    def validate_proxy(self, proxy: dict[str, Any]) -> bool:
        """Validate proxy reachability using a socket health check."""
        timeout = float(self.settings.get("proxy", {}).get("healthcheck_timeout_seconds", 3))
        key = self._key(proxy)
        try:
            with socket.create_connection((proxy["host"], int(proxy["port"])), timeout=timeout):
                self.proxy_stats[key]["healthy"] = True
        except OSError:
            self.proxy_stats[key]["healthy"] = False
            self.proxy_stats[key]["failures"] += 1
        finally:
            self.proxy_stats[key]["last_checked"] = datetime.now(timezone.utc).isoformat()

        return bool(self.proxy_stats[key]["healthy"])

    def get_proxy_stats(self) -> dict[str, dict[str, Any]]:
        """Return proxy health and usage metrics."""
        return self.proxy_stats
