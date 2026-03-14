"""
config.py — Central configuration. All values loaded from environment variables.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── IVASMS credentials ────────────────────────────────────────────────────────
IVASMS_EMAIL: str = os.getenv("IVASMS_EMAIL", "")
IVASMS_PASSWORD: str = os.getenv("IVASMS_PASSWORD", "")

if not IVASMS_EMAIL or not IVASMS_PASSWORD:
    raise EnvironmentError("IVASMS_EMAIL and IVASMS_PASSWORD must be set.")

# ── Telegram ───────────────────────────────────────────────────────────────────
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
CHAT_ID: str = os.getenv("CHAT_ID", "")

if not BOT_TOKEN:
    raise EnvironmentError("BOT_TOKEN must be set.")
if not CHAT_ID:
    raise EnvironmentError("CHAT_ID must be set.")

# ── Monitor settings ───────────────────────────────────────────────────────────
POLL_INTERVAL: int = int(os.getenv("POLL_INTERVAL", "3"))       # seconds between polls
SESSION_TIMEOUT: int = int(os.getenv("SESSION_TIMEOUT", "7200")) # 2 hours

# ── Storage ────────────────────────────────────────────────────────────────────
JSON_FILE: str = os.getenv("JSON_FILE", "sms_statistics.json")

# ── Logging ────────────────────────────────────────────────────────────────────
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
