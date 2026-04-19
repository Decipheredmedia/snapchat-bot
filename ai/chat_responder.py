"""TensorFlow-assisted chat response engine with safety filtering."""

from __future__ import annotations

import logging
import random
import re
from collections import defaultdict
from typing import Any

import yaml

try:
    import tensorflow as tf
except Exception:  # pragma: no cover
    tf = None


class ChatResponder:
    """Generate safe conversational responses with intent awareness."""

    def __init__(self, config_path: str = "config/settings.yaml") -> None:
        """Initialize responder, templates, and optional TensorFlow model."""
        self.logger = logging.getLogger(self.__class__.__name__)
        with open(config_path, "r", encoding="utf-8") as handle:
            self.config = yaml.safe_load(handle) or {}
        self.model = None
        self.model_path = self.config.get("ai", {}).get("model_path", "")
        self.conversation_state: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        self.blocked_terms = {"illegal", "exploit", "hate", "violence"}
        self.templates = {
            "greeting": ["Hey! Great to hear from you 😊", "Hi there! What can I help with today?"],
            "question": ["Great question — here’s what I can share:", "Happy to help. Here’s a quick answer:"],
            "purchase_interest": ["Awesome — I can send you premium details and pricing.", "Love that interest! I can share payment options right away."],
            "complaint": ["I’m sorry about that. Let’s fix it quickly.", "Thanks for flagging this — I’ll make it right."],
            "general": ["Got it. Tell me a bit more so I can help better.", "Thanks for the message — I’m here to help."],
        }
        self.load_model(self.model_path)

    def load_model(self, model_path: str) -> None:
        """Load TensorFlow model if available; otherwise initialize fallback model."""
        if not tf:
            self.logger.warning("TensorFlow not available; using rules-only response engine")
            self.model = None
            return
        try:
            self.model = tf.keras.models.load_model(model_path)
            self.logger.info("Loaded TensorFlow model from %s", model_path)
        except Exception:
            self.model = tf.keras.Sequential(
                [
                    tf.keras.layers.Input(shape=(8,)),
                    tf.keras.layers.Dense(16, activation="relu"),
                    tf.keras.layers.Dense(5, activation="softmax"),
                ]
            )
            self.model.compile(optimizer="adam", loss="categorical_crossentropy")
            self.logger.info("Initialized fallback TensorFlow model")

    def classify_intent(self, message: str) -> str:
        """Classify message intent into predefined categories."""
        text = message.lower().strip()
        if any(word in text for word in {"hi", "hello", "hey"}):
            return "greeting"
        if any(word in text for word in {"how", "what", "why", "when", "where", "?"}):
            return "question"
        if any(word in text for word in {"buy", "price", "purchase", "pay", "premium"}):
            return "purchase_interest"
        if any(word in text for word in {"bad", "issue", "problem", "refund", "complaint"}):
            return "complaint"
        return "general"

    def get_conversation_context(self, account: str, chat_id: str) -> list[str]:
        """Return tracked conversation history for account/chat pair."""
        return self.conversation_state[account][chat_id]

    def _contains_flagged_content(self, text: str) -> bool:
        return any(term in text.lower() for term in self.blocked_terms)

    def generate_response(self, conversation_history: list[str], context: dict[str, Any]) -> str:
        """Generate a response using intent templates and TensorFlow variation scoring."""
        message = conversation_history[-1] if conversation_history else ""
        if self._contains_flagged_content(message):
            return "I can’t help with unsafe or prohibited requests, but I can help with account and content questions."

        intent = self.classify_intent(message)
        base = random.choice(self.templates[intent])

        if self.model is not None and tf is not None:
            features = tf.convert_to_tensor([[len(message), message.count("!"), message.count("?"), len(conversation_history), 1, 1, 1, 1]], dtype=tf.float32)
            confidence = float(tf.reduce_max(self.model(features)).numpy())
            if confidence > 0.5:
                base = f"{base} (I’m {int(confidence * 100)}% confident this helps.)"

        product_hint = context.get("product")
        if intent == "purchase_interest" and product_hint:
            base = f"{base} Product: {product_hint}."
        return base
