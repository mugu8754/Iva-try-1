# IVASMS Telegram Monitor Bot

A fully-featured Telegram bot that monitors your **IVASMS** account in real time and pushes instant alerts for every new SMS received across all your ranges.

---

## Features

| Feature | Description |
|---|---|
| 📩 Real-time alerts | New SMS pushed instantly to your Telegram chat/group |
| 📊 Statistics | Today's counts, paid/unpaid split, revenue per range |
| 📋 Range listing | All active ranges with live counts |
| 📅 Custom date stats | Fetch stats for any date range on demand |
| 🔄 Auto re-login | Session refreshes every 2 hours automatically |
| ▶️ Start/Stop monitor | Full control from Telegram inline buttons |
| 🕐 SMS history | View last 5 SMS received with `/latest` |
| 🔍 Range detail | Deep-dive into any specific range |
| 🧹 Cache management | Clear stored data on demand |
| ℹ️ Status dashboard | Live bot + monitor health info |

---

## Bot Commands

```
/start        — Main menu with inline buttons
/help         — All available commands
/stats        — Today's SMS statistics
/ranges       — List all cached ranges
/monitor      — Start live monitoring
/stop         — Stop live monitoring
/status       — Bot & monitor health
/refresh      — Force re-login to IVASMS
/custom       — Stats for a custom date range
/clearcache   — Clear stored statistics
/latest       — Show last 5 SMS received
/range <name> — Details for a specific range
/cancel       — Cancel an ongoing conversation
```

---

## Local Setup

### 1. Clone / copy the project
```bash
git clone <your-repo>
cd ivasms-bot
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure environment
```bash
cp .env.example .env
# Edit .env with your credentials
```

### 4. Run
```bash
python bot.py
```

---

## Deploy to Render

### Prerequisites
- A [Render](https://render.com) account (free tier works)
- Your code pushed to a GitHub/GitLab repo

### Steps

1. **Push to GitHub**
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git remote add origin https://github.com/youruser/ivasms-bot
   git push -u origin main
   ```

2. **Create a new service on Render**
   - Go to https://dashboard.render.com
   - Click **New → Background Worker**
   - Connect your GitHub repo
   - Render will auto-detect `render.yaml`

3. **Set environment variables** in Render dashboard:
   | Key | Value |
   |---|---|
   | `IVASMS_EMAIL` | your IVASMS email |
   | `IVASMS_PASSWORD` | your IVASMS password |
   | `BOT_TOKEN` | Telegram bot token from @BotFather |
   | `CHAT_ID` | Your Telegram chat or group ID |
   | `POLL_INTERVAL` | `3` (seconds, optional) |
   | `SESSION_TIMEOUT` | `7200` (optional) |

4. **Deploy** — Render will build and start the worker automatically.

> ℹ️ The free tier on Render may spin down after inactivity for *web services*, but **Background Workers** stay alive continuously.

---

## Finding Your CHAT_ID

- For a **personal chat**: message `@userinfobot` on Telegram
- For a **group**: add `@userinfobot` to the group, it will show the group ID (starts with `-100...`)

---

## Project Structure

```
ivasms-bot/
├── bot.py           # Main bot — all Telegram handlers & monitor loop
├── ivasms.py        # IVASMS scraping client (login, stats, messages)
├── storage.py       # JSON persistence layer (ranges + SMS history)
├── config.py        # Environment variable loading & validation
├── requirements.txt # Python dependencies
├── render.yaml      # One-click Render deployment config
└── .env.example     # Environment variable template
```

---

## Notes

- The bot uses **long polling** (no webhook needed) — works perfectly on Render workers.
- IVASMS doesn't provide an official API; this bot scrapes the web interface.
- If IVASMS changes their HTML structure, the parsers in `ivasms.py` may need updating.
