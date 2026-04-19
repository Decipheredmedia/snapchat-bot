"""API key authentication helpers and FastAPI dependency."""

from __future__ import annotations

import secrets
from typing import Any

import yaml
from fastapi import Depends, Header, HTTPException, status


class APIKeyAuth:
    """Manage API keys and verify incoming requests."""

    def __init__(self, config_path: str = "config/settings.yaml") -> None:
        """Load API keys from configuration."""
        with open(config_path, "r", encoding="utf-8") as handle:
            cfg = yaml.safe_load(handle) or {}
        keys = cfg.get("auth", {}).get("api_keys", [])
        self.api_keys: set[str] = set(keys)

    def verify_api_key(self, key: str) -> bool:
        """Validate API key."""
        return key in self.api_keys

    def create_api_key(self) -> str:
        """Generate and store a new API key."""
        key = secrets.token_urlsafe(32)
        self.api_keys.add(key)
        return key

    def revoke_api_key(self, key: str) -> bool:
        """Revoke an API key if present."""
        if key not in self.api_keys:
            return False
        self.api_keys.remove(key)
        return True


auth_manager = APIKeyAuth()


def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> str:
    """FastAPI dependency for route protection."""
    if not x_api_key or not auth_manager.verify_api_key(x_api_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing API key")
    return x_api_key
