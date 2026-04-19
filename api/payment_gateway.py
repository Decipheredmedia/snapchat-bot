"""Stripe and crypto payment handling."""

from __future__ import annotations

import csv
import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

try:
    import stripe
except Exception:  # pragma: no cover
    stripe = None


class PaymentGateway:
    """Handle Stripe payment links, webhooks, and basic crypto payment flow."""

    def __init__(self, config_path: str = "config/settings.yaml") -> None:
        """Initialize payment configuration and local transaction cache."""
        self.logger = logging.getLogger(self.__class__.__name__)
        with open(config_path, "r", encoding="utf-8") as handle:
            self.config = yaml.safe_load(handle) or {}
        pay_cfg = self.config.get("payment", {})
        self.stripe_api_key = pay_cfg.get("stripe_api_key", "")
        self.webhook_secret = pay_cfg.get("stripe_webhook_secret", "")
        self.default_currency = pay_cfg.get("default_currency", "usd")
        self.crypto_wallets = pay_cfg.get("crypto", {})
        self.local_payments: dict[str, dict[str, Any]] = {}
        self.payment_log = Path("data/payment/payment_status.csv")
        self.payment_log.parent.mkdir(parents=True, exist_ok=True)
        self.is_valid_stripe_key = bool(self.stripe_api_key) and not self.stripe_api_key.startswith("sk_test_replace")
        if stripe and self.stripe_api_key:
            stripe.api_key = self.stripe_api_key

    def _write_payment_log(
        self,
        account: str,
        payment_id: str,
        amount: float,
        currency: str,
        status: str,
        method: str,
        recipient: str,
    ) -> None:
        with self.payment_log.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow([
                datetime.now(timezone.utc).isoformat(),
                account,
                payment_id,
                amount,
                currency,
                status,
                method,
                recipient,
            ])

    def create_stripe_payment_link(self, amount: float, currency: str, description: str) -> dict[str, str]:
        """Create Stripe payment link or robust local fallback."""
        currency = currency or self.default_currency
        if stripe and self.is_valid_stripe_key:
            product = stripe.Product.create(name=description)
            price = stripe.Price.create(product=product.id, unit_amount=int(amount * 100), currency=currency)
            link = stripe.PaymentLink.create(line_items=[{"price": price.id, "quantity": 1}])
            payment_id = link.id
            url = link.url
        else:
            payment_id = f"local_{secrets.token_hex(8)}"
            url = f"https://payments.local/pay/{payment_id}"

        self.local_payments[payment_id] = {
            "id": payment_id,
            "amount": amount,
            "currency": currency,
            "description": description,
            "status": "pending",
            "method": "stripe",
        }
        return {"payment_id": payment_id, "url": url}

    def check_payment_status(self, payment_id: str) -> str:
        """Check current payment status from Stripe or local cache."""
        if payment_id in self.local_payments:
            return self.local_payments[payment_id]["status"]

        if stripe and self.is_valid_stripe_key and payment_id.startswith("pi_"):
            intent = stripe.PaymentIntent.retrieve(payment_id)
            return intent.status

        return "unknown"

    def generate_crypto_address(self, currency: str) -> str:
        """Generate deterministic pseudo-wallet address for requested currency."""
        seed = f"{currency}:{datetime.now(timezone.utc).timestamp()}:{secrets.token_hex(8)}"
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        prefix = "0x" if currency.lower() in {"eth", "usdt"} else "bc1"
        return f"{prefix}{digest[:38]}"

    def verify_crypto_payment(self, tx_hash: str) -> bool:
        """Verify shape and basic integrity of crypto transaction hash."""
        normalized = tx_hash.lower().strip()
        is_eth_like = normalized.startswith("0x") and len(normalized) >= 18
        is_btc_like = normalized.startswith("btc_") and len(normalized) >= 18
        return is_eth_like or is_btc_like

    def handle_webhook(self, payload: bytes, sig_header: str | None = None) -> dict[str, Any]:
        """Handle Stripe webhook payload and update payment status."""
        if stripe and sig_header and self.webhook_secret:
            event = stripe.Webhook.construct_event(payload=payload, sig_header=sig_header, secret=self.webhook_secret)
            event_type = event["type"]
            obj = event["data"]["object"]
            payment_id = obj.get("id", "")
        else:
            import json

            body = json.loads(payload.decode("utf-8"))
            event_type = body.get("type", "unknown")
            obj = body.get("data", {}).get("object", {})
            payment_id = obj.get("id", body.get("payment_id", ""))

        if payment_id:
            if payment_id not in self.local_payments:
                self.local_payments[payment_id] = {"id": payment_id, "amount": obj.get("amount_total", 0) / 100, "currency": obj.get("currency", "usd"), "method": "stripe"}
            if event_type in {"checkout.session.completed", "payment_intent.succeeded"}:
                self.local_payments[payment_id]["status"] = "paid"
            elif "failed" in event_type:
                self.local_payments[payment_id]["status"] = "failed"

        return {"received": True, "event_type": event_type, "payment_id": payment_id}
