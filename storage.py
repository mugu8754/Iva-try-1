"""
storage.py — JSON-backed persistence layer.
Stores range statistics and recent SMS alerts.
"""

import json
import logging
import os
from typing import Any

logger = logging.getLogger("ivasms-bot.storage")

SMS_HISTORY_FILE = "sms_history.json"
MAX_SMS_HISTORY = 100  # keep last N SMS in history


class Storage:
    def __init__(self, filepath: str):
        self.filepath = filepath

    # ── Range statistics ──────────────────────────────────────────────────────

    def save(self, ranges: list[dict]) -> None:
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(ranges, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save stats: {e}")

    def load(self) -> list[dict]:
        if not os.path.exists(self.filepath):
            return []
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load stats: {e}")
            return []

    def clear(self) -> None:
        try:
            if os.path.exists(self.filepath):
                os.remove(self.filepath)
            if os.path.exists(SMS_HISTORY_FILE):
                os.remove(SMS_HISTORY_FILE)
            logger.info("Cache cleared.")
        except Exception as e:
            logger.error(f"Failed to clear cache: {e}")

    # ── SMS history ───────────────────────────────────────────────────────────

    def save_sms(self, sms: dict) -> None:
        history = self._load_history()
        history.insert(0, sms)
        history = history[:MAX_SMS_HISTORY]
        try:
            with open(SMS_HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(history, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save SMS history: {e}")

    def load_latest(self, n: int = 5) -> list[dict]:
        return self._load_history()[:n]

    def _load_history(self) -> list[dict]:
        if not os.path.exists(SMS_HISTORY_FILE):
            return []
        try:
            with open(SMS_HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load SMS history: {e}")
            return []
