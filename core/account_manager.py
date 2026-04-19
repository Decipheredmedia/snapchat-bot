"""Account persistence and lifecycle management."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import JSON, Boolean, DateTime, String, create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


class Base(DeclarativeBase):
    """SQLAlchemy declarative base."""


class AccountRecord(Base):
    """Database model for Snapchat accounts."""

    __tablename__ = "accounts"

    username: Mapped[str] = mapped_column(String(100), primary_key=True)
    password: Mapped[str] = mapped_column(String(255), nullable=False)
    assigned_proxy: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    device_fingerprint: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    session_status: Mapped[str] = mapped_column(String(32), default="stopped")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_active: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    add_count: Mapped[int] = mapped_column(default=0)
    error_count: Mapped[int] = mapped_column(default=0)


@dataclass
class AccountHealth:
    """Runtime health view for an account."""

    username: str
    session_status: str
    proxy_assigned: bool
    last_active: str | None
    add_count: int
    error_count: int


class AccountManager:
    """Manage Snapchat accounts with isolated state and database persistence."""

    def __init__(self, config_path: str = "config/settings.yaml") -> None:
        """Initialize account storage and DB engine from YAML config."""
        self.logger = logging.getLogger(self.__class__.__name__)
        self.config = self._load_config(config_path)
        db = self.config.get("database", {})
        postgres_url = (
            f"postgresql+psycopg2://{db.get('user', 'user')}:{db.get('password', 'pass')}"
            f"@{db.get('host', 'localhost')}:{db.get('port', 5432)}/{db.get('name', 'snapchat_bot')}"
        )
        sqlite_fallback = "sqlite:///data/snapchat_bot.db"
        Path("data").mkdir(parents=True, exist_ok=True)
        try:
            self.engine = create_engine(postgres_url, echo=bool(db.get("echo", False)), future=True)
            with self.engine.connect() as conn:
                conn.execute(select(1))
            self.logger.info("Connected to PostgreSQL")
        except Exception as exc:
            self.logger.warning("PostgreSQL unavailable (%s), using SQLite fallback", exc)
            self.engine = create_engine(sqlite_fallback, future=True)

        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)

    @staticmethod
    def _load_config(path: str) -> dict[str, Any]:
        with open(path, "r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}

    def add_account(self, username: str, password: str, device_fingerprint: dict[str, Any] | None = None) -> dict[str, Any]:
        """Add a new account or update credentials if it already exists."""
        with self.session_factory() as db:
            record = db.get(AccountRecord, username)
            if record is None:
                record = AccountRecord(
                    username=username,
                    password=password,
                    device_fingerprint=device_fingerprint or {},
                    session_status="stopped",
                    is_active=True,
                    last_active=datetime.now(timezone.utc),
                )
                db.add(record)
                action = "created"
            else:
                record.password = password
                if device_fingerprint:
                    record.device_fingerprint = device_fingerprint
                record.last_active = datetime.now(timezone.utc)
                action = "updated"
            db.commit()
            self.logger.info("Account %s %s", username, action)
            return self._to_dict(record)

    def remove_account(self, username: str) -> bool:
        """Soft delete account by marking inactive and stopping session."""
        with self.session_factory() as db:
            record = db.get(AccountRecord, username)
            if not record:
                return False
            record.is_active = False
            record.session_status = "stopped"
            record.last_active = datetime.now(timezone.utc)
            db.commit()
            self.logger.info("Account %s deactivated", username)
            return True

    def get_account(self, username: str) -> dict[str, Any] | None:
        """Fetch a single account."""
        with self.session_factory() as db:
            record = db.get(AccountRecord, username)
            return self._to_dict(record) if record else None

    def list_active_accounts(self) -> list[dict[str, Any]]:
        """List all active accounts."""
        with self.session_factory() as db:
            rows = db.execute(select(AccountRecord).where(AccountRecord.is_active.is_(True))).scalars().all()
            return [self._to_dict(row) for row in rows]

    def assign_proxy(self, username: str, proxy: dict[str, Any]) -> bool:
        """Assign an isolated proxy to an account."""
        with self.session_factory() as db:
            record = db.get(AccountRecord, username)
            if not record:
                return False
            record.assigned_proxy = proxy
            record.last_active = datetime.now(timezone.utc)
            db.commit()
            self.logger.info("Assigned proxy %s:%s to %s", proxy.get("host"), proxy.get("port"), username)
            return True

    def update_fingerprint(self, username: str) -> dict[str, Any] | None:
        """Regenerate and persist a device fingerprint."""
        with self.session_factory() as db:
            record = db.get(AccountRecord, username)
            if not record:
                return None
            fingerprint = {
                "android_id": f"aid_{username}_{int(datetime.now(timezone.utc).timestamp())}",
                "locale": "en_US",
                "timezone": "UTC",
                "app_version": "12.0.0",
            }
            record.device_fingerprint = fingerprint
            record.last_active = datetime.now(timezone.utc)
            db.commit()
            return fingerprint

    def get_health_status(self, username: str) -> dict[str, Any] | None:
        """Return health metrics for a single account."""
        with self.session_factory() as db:
            record = db.get(AccountRecord, username)
            if not record:
                return None
            health = AccountHealth(
                username=record.username,
                session_status=record.session_status,
                proxy_assigned=bool(record.assigned_proxy),
                last_active=record.last_active.isoformat() if record.last_active else None,
                add_count=record.add_count,
                error_count=record.error_count,
            )
            return health.__dict__

    def update_session_status(self, username: str, status: str) -> None:
        """Update runtime session status and activity timestamp."""
        with self.session_factory() as db:
            record = db.get(AccountRecord, username)
            if not record:
                return
            record.session_status = status
            record.last_active = datetime.now(timezone.utc)
            db.commit()

    def increment_add_count(self, username: str) -> None:
        """Increment successful add count for an account."""
        with self.session_factory() as db:
            record = db.get(AccountRecord, username)
            if not record:
                return
            record.add_count += 1
            record.last_active = datetime.now(timezone.utc)
            db.commit()

    def increment_error_count(self, username: str) -> None:
        """Increment error count for an account."""
        with self.session_factory() as db:
            record = db.get(AccountRecord, username)
            if not record:
                return
            record.error_count += 1
            record.last_active = datetime.now(timezone.utc)
            db.commit()

    @staticmethod
    def _to_dict(record: AccountRecord) -> dict[str, Any]:
        return {
            "username": record.username,
            "password": record.password,
            "assigned_proxy": record.assigned_proxy,
            "device_fingerprint": record.device_fingerprint,
            "session_status": record.session_status,
            "is_active": record.is_active,
            "last_active": record.last_active.isoformat() if record.last_active else None,
            "add_count": record.add_count,
            "error_count": record.error_count,
        }
