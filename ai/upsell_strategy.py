"""Upsell timing and conversion analytics."""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone
from typing import Any


class UpsellStrategy:
    """Determine upsell timing and track conversion performance."""

    def __init__(self) -> None:
        """Initialize product catalog and conversion storage."""
        self.logger = logging.getLogger(self.__class__.__name__)
        self.product_catalog = {
            "premium_snap_pack": {"price": 19.99, "currency": "usd"},
            "vip_chat_access": {"price": 49.99, "currency": "usd"},
            "weekly_drop": {"price": 9.99, "currency": "usd"},
        }
        self.conversions: list[dict[str, Any]] = []

    def should_upsell(self, conversation_history: list[str]) -> bool:
        """Return True when positive engagement indicates upsell readiness."""
        positive_markers = {"yes", "great", "awesome", "love", "interested", "want"}
        score = sum(1 for msg in conversation_history if any(token in msg.lower() for token in positive_markers))
        return len(conversation_history) >= 3 and score >= 2

    def get_upsell_message(self, context: dict[str, Any], product: str) -> str:
        """Build contextual upsell copy from product catalog."""
        item = self.product_catalog.get(product)
        if not item:
            return "I can share premium options if you tell me what kind of content you want."
        user_tone = context.get("tone", "friendly")
        intro = "You might like this next:" if user_tone == "friendly" else "Recommended upgrade:"
        return f"{intro} {product} for {item['price']} {item['currency'].upper()}. Want the secure payment link?"

    def track_conversion(self, account: str, chat_id: str, product: str) -> dict[str, Any]:
        """Record successful upsell conversion event."""
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "account": account,
            "chat_id": chat_id,
            "product": product,
        }
        self.conversions.append(event)
        self.logger.info("Tracked conversion for %s on %s", account, product)
        return event

    def get_upsell_stats(self) -> dict[str, Any]:
        """Return aggregate upsell analytics."""
        by_product = Counter(event["product"] for event in self.conversions)
        return {
            "total_conversions": len(self.conversions),
            "by_product": dict(by_product),
        }
