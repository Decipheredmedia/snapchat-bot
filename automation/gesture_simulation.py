"""Human-like mobile gesture simulation via Appium."""

from __future__ import annotations

import logging
import random
import time
from typing import Any


class GestureSimulator:
    """Perform jittered, randomized touch interactions for stealth automation."""

    def __init__(self, driver: Any) -> None:
        """Bind simulator to an Appium/WebDriver session."""
        self.driver = driver
        self.logger = logging.getLogger(self.__class__.__name__)

    @staticmethod
    def random_pause(min_seconds: float = 0.5, max_seconds: float = 3.0) -> float:
        """Sleep for randomized human-like delay and return pause duration."""
        pause = random.uniform(min_seconds, max_seconds)
        time.sleep(pause)
        return pause

    @staticmethod
    def _jitter(value: int, max_offset: int = 7) -> int:
        return value + random.randint(-max_offset, max_offset)

    def tap(self, element: Any) -> None:
        """Tap an element with coordinate jitter and delay."""
        location = element.location
        size = element.size
        x = self._jitter(int(location["x"] + size["width"] / 2))
        y = self._jitter(int(location["y"] + size["height"] / 2))
        self.driver.execute_script("mobile: clickGesture", {"x": x, "y": y})
        self.random_pause()

    def double_tap(self, element: Any) -> None:
        """Double tap an element with micro-delay and jitter."""
        self.tap(element)
        self.random_pause(0.08, 0.25)
        self.tap(element)

    def long_press(self, element: Any) -> None:
        """Long press element for randomized duration."""
        location = element.location
        size = element.size
        x = self._jitter(int(location["x"] + size["width"] / 2))
        y = self._jitter(int(location["y"] + size["height"] / 2))
        duration = int(random.uniform(800, 1800))
        self.driver.execute_script("mobile: longClickGesture", {"x": x, "y": y, "duration": duration})
        self.random_pause()

    def swipe(self, direction: str, duration: int = 700) -> None:
        """Swipe in a direction with variable speed and jitter."""
        size = self.driver.get_window_size()
        mid_x = int(size["width"] * 0.5)
        mid_y = int(size["height"] * 0.5)
        offsets = {
            "up": (0, -int(size["height"] * 0.35)),
            "down": (0, int(size["height"] * 0.35)),
            "left": (-int(size["width"] * 0.35), 0),
            "right": (int(size["width"] * 0.35), 0),
        }
        dx, dy = offsets.get(direction, offsets["up"])
        start_x = self._jitter(mid_x)
        start_y = self._jitter(mid_y)
        end_x = self._jitter(mid_x + dx)
        end_y = self._jitter(mid_y + dy)
        self.driver.execute_script(
            "mobile: swipeGesture",
            {"startX": start_x, "startY": start_y, "endX": end_x, "endY": end_y, "duration": duration},
        )
        self.random_pause()

    def scroll_to(self, element: Any) -> bool:
        """Scroll toward element until displayed or retries exhausted."""
        for _ in range(6):
            try:
                if element.is_displayed():
                    return True
            except Exception:
                pass
            self.swipe("up", duration=random.randint(400, 1300))
        return False

    def type_text(self, element: Any, text: str) -> None:
        """Type text with character-level timing variation."""
        element.click()
        self.random_pause(0.2, 0.7)
        try:
            element.clear()
        except Exception:
            pass
        for char in text:
            element.send_keys(char)
            self.random_pause(0.05, 0.25)
        self.random_pause()

    def simulate_human_scroll(self) -> None:
        """Run multiple variable-speed scroll gestures."""
        for _ in range(random.randint(2, 5)):
            self.swipe(random.choice(["up", "down"]), duration=random.randint(450, 1500))
            self.random_pause(0.4, 1.8)
