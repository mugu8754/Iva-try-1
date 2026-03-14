import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup
from telegram import (
    Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler,
    ContextTypes, ConversationHandler, MessageHandler, filters
)

from config import (
    BOT_TOKEN, CHAT_ID, IVASMS_EMAIL, IVASMS_PASSWORD,
    POLL_INTERVAL, SESSION_TIMEOUT, JSON_FILE, LOG_LEVEL
)
from ivasms import IVASMSClient
from storage import Storage

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=getattr(logging, LOG_LEVEL, logging.INFO),
)
logger = logging.getLogger("ivasms-bot")

# ── State machine for ConversationHandler ────────────────────────────────────
AWAIT_DATE_FROM, AWAIT_DATE_TO = range(2)

# ── Globals ──────────────────────────────────────────────────────────────────
storage = Storage(JSON_FILE)
monitor_task: asyncio.Task | None = None
monitor_running = False


# ═══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def fmt_sms(sms: dict) -> str:
    return (
        f"📩 *New SMS Received*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🕐 *Time:* `{sms['timestamp']}`\n"
        f"📞 *Number:* `+{sms['number']}`\n"
        f"📡 *Range:* `{sms['range']}`\n"
        f"💬 *Message:*\n`{sms['message']}`\n"
        f"💰 *Revenue:* `{sms['revenue']}`"
    )


def fmt_stats(ranges: list) -> str:
    if not ranges:
        return "📭 No SMS data found for this period."
    lines = ["📊 *SMS Statistics*\n━━━━━━━━━━━━━━━━━━━━"]
    total_count = total_rev = 0
    for r in ranges:
        lines.append(
            f"\n📡 *{r['range_name']}*\n"
            f"  • Total: `{r['count']}`  Paid: `{r['paid']}`  Unpaid: `{r['unpaid']}`\n"
            f"  • Revenue: `{r['revenue']}`"
        )
        total_count += r.get("count", 0)
        try:
            total_rev += float(str(r.get("revenue", 0)).replace(",", ""))
        except Exception:
            pass
    lines.append(f"\n━━━━━━━━━━━━━━━━━━━━\n💎 *Total:* `{total_count}` SMS | `{total_rev:.2f}` revenue")
    return "\n".join(lines)


def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Statistics", callback_data="stats"),
            InlineKeyboardButton("📋 Ranges", callback_data="ranges"),
        ],
        [
            InlineKeyboardButton("📱 My Numbers", callback_data="numbers"),
            InlineKeyboardButton("ℹ️ Status", callback_data="status"),
        ],
        [
            InlineKeyboardButton("▶️ Start Monitor", callback_data="monitor_start"),
            InlineKeyboardButton("⏹ Stop Monitor", callback_data="monitor_stop"),
        ],
        [
            InlineKeyboardButton("🔄 Refresh Login", callback_data="refresh_login"),
            InlineKeyboardButton("📅 Custom Date", callback_data="custom_date"),
        ],
        [
            InlineKeyboardButton("🧹 Clear Cache", callback_data="clear_cache"),
        ],
    ])


def fmt_numbers(numbers: list) -> str:
    if not numbers:
        return "📭 No virtual numbers found on this account."
    lines = [f"📱 *Available Numbers* ({len(numbers)} total)\n━━━━━━━━━━━━━━━━━━━━"]
    for i, n in enumerate(numbers, 1):
        status_emoji = "🟢" if str(n.get("status", "")).lower() == "active" else "🔴"
        lines.append(
            f"\n*{i}.* `+{n['number']}`\n"
            f"  {status_emoji} Status: `{n.get('status', '—')}`\n"
            f"  🌍 Country/Range: `{n.get('country', '—')}`\n"
            f"  ⏳ Expires: `{n.get('expires', '—')}`"
        )
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
#  COMMAND HANDLERS
# ═══════════════════════════════════════════════════════════════════════════════

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Welcome to IVASMS Monitor Bot!*\n\n"
        "This bot monitors your IVASMS account and sends real-time SMS notifications.\n\n"
        "Use the menu below or type /help for all commands.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_menu_keyboard(),
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 *Available Commands*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "/start — Main menu\n"
        "/help — This help message\n"
        "/stats — Today's SMS statistics\n"
        "/ranges — List all active ranges\n"
        "/numbers — List all virtual numbers on account\n"
        "/monitor — Start live monitoring\n"
        "/stop — Stop live monitoring\n"
        "/status — Bot & monitor status\n"
        "/refresh — Force re-login to IVASMS\n"
        "/custom — Stats for custom date range\n"
        "/clearcache — Clear saved statistics\n"
        "/latest — Show latest 5 SMS received\n"
        "/range <name> — Details for a specific range\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ Fetching statistics…")
    today = datetime.now()
    from_date = today.strftime("%m/%d/%Y")
    to_date = (today + timedelta(days=1)).strftime("%m/%d/%Y")
    try:
        client = IVASMSClient()
        client.login()
        ranges = client.fetch_statistics(from_date, to_date)
        await msg.edit_text(fmt_stats(ranges), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await msg.edit_text(f"❌ Error: {e}")


async def cmd_ranges(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ranges = storage.load()
    if not ranges:
        await update.message.reply_text("📭 No cached ranges. Run /stats first.")
        return
    lines = ["📡 *Active Ranges*\n━━━━━━━━━━━━━━━━━━━━"]
    for r in ranges:
        lines.append(f"• `{r['range_name']}` — {r['count']} SMS | Rev: {r['revenue']}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)




async def cmd_numbers(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ Fetching your virtual numbers…")
    try:
        client = IVASMSClient()
        client.login()
        numbers = client.fetch_available_numbers()
        text = fmt_numbers(numbers)
        # Split into chunks if too long (Telegram 4096 char limit)
        if len(text) > 4000:
            chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
            await msg.edit_text(chunks[0], parse_mode=ParseMode.MARKDOWN)
            for chunk in chunks[1:]:
                await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)
        else:
            await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await msg.edit_text(f"❌ Error fetching numbers: {e}")

async def cmd_monitor(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global monitor_task, monitor_running
    if monitor_running:
        await update.message.reply_text("✅ Monitor is already running.")
        return
    monitor_running = True
    monitor_task = asyncio.create_task(monitor_loop(ctx.application))
    await update.message.reply_text(
        "▶️ *Live monitor started!*\n"
        f"Polling every {POLL_INTERVAL}s. Use /stop to halt.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global monitor_running
    if not monitor_running:
        await update.message.reply_text("⏹ Monitor is not running.")
        return
    monitor_running = False
    if monitor_task:
        monitor_task.cancel()
    await update.message.reply_text("⏹ *Monitor stopped.*", parse_mode=ParseMode.MARKDOWN)


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    state = "🟢 Running" if monitor_running else "🔴 Stopped"
    ranges = storage.load()
    await update.message.reply_text(
        f"ℹ️ *Bot Status*\n━━━━━━━━━━━━━━━━━━━━\n"
        f"Monitor: {state}\n"
        f"Cached ranges: `{len(ranges)}`\n"
        f"Poll interval: `{POLL_INTERVAL}s`\n"
        f"Account: `{IVASMS_EMAIL}`",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_refresh(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🔄 Re-logging into IVASMS…")
    try:
        client = IVASMSClient()
        client.login()
        await msg.edit_text("✅ Successfully logged in to IVASMS.")
    except Exception as e:
        await msg.edit_text(f"❌ Login failed: {e}")


async def cmd_clearcache(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    storage.clear()
    await update.message.reply_text("🧹 Cache cleared.")


async def cmd_latest(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    latest = storage.load_latest(5)
    if not latest:
        await update.message.reply_text("📭 No recent SMS in cache.")
        return
    for sms in latest:
        await update.message.reply_text(fmt_sms(sms), parse_mode=ParseMode.MARKDOWN)


async def cmd_range_detail(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: /range <range_name>")
        return
    range_name = " ".join(ctx.args)
    ranges = storage.load()
    match = next((r for r in ranges if r["range_name"].lower() == range_name.lower()), None)
    if not match:
        await update.message.reply_text(f"❌ Range `{range_name}` not found in cache.", parse_mode=ParseMode.MARKDOWN)
        return
    text = (
        f"📡 *Range: {match['range_name']}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Total SMS: `{match['count']}`\n"
        f"Paid: `{match['paid']}`\n"
        f"Unpaid: `{match['unpaid']}`\n"
        f"Revenue: `{match['revenue']}`"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# ── Custom date conversation ─────────────────────────────────────────────────

async def cmd_custom(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📅 Enter *FROM* date (MM/DD/YYYY):",
        parse_mode=ParseMode.MARKDOWN,
    )
    return AWAIT_DATE_FROM


async def custom_from(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["custom_from"] = update.message.text.strip()
    await update.message.reply_text("📅 Enter *TO* date (MM/DD/YYYY):", parse_mode=ParseMode.MARKDOWN)
    return AWAIT_DATE_TO


async def custom_to(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    from_date = ctx.user_data.get("custom_from")
    to_date = update.message.text.strip()
    msg = await update.message.reply_text("⏳ Fetching statistics…")
    try:
        client = IVASMSClient()
        client.login()
        ranges = client.fetch_statistics(from_date, to_date)
        await msg.edit_text(fmt_stats(ranges), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await msg.edit_text(f"❌ Error: {e}")
    return ConversationHandler.END


async def cancel_conv(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Cancelled.")
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════════════════════════
#  CALLBACK QUERY HANDLER (inline buttons)
# ═══════════════════════════════════════════════════════════════════════════════

async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global monitor_running, monitor_task
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "stats":
        await query.edit_message_text("⏳ Fetching statistics…")
        today = datetime.now()
        from_date = today.strftime("%m/%d/%Y")
        to_date = (today + timedelta(days=1)).strftime("%m/%d/%Y")
        try:
            client = IVASMSClient()
            client.login()
            ranges = client.fetch_statistics(from_date, to_date)
            await query.edit_message_text(
                fmt_stats(ranges),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="menu")]]),
            )
        except Exception as e:
            await query.edit_message_text(f"❌ Error: {e}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="menu")]]))

    elif data == "ranges":
        ranges = storage.load()
        if not ranges:
            text = "📭 No cached ranges. Fetch stats first."
        else:
            lines = ["📡 *Active Ranges*\n━━━━━━━━━━━━━━━━━━━━"]
            for r in ranges:
                lines.append(f"• `{r['range_name']}` — {r['count']} SMS | Rev: {r['revenue']}")
            text = "\n".join(lines)
        await query.edit_message_text(
            text, parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="menu")]]),
        )


    elif data == "numbers":
        await query.edit_message_text("⏳ Fetching your virtual numbers…")
        try:
            client = IVASMSClient()
            client.login()
            numbers = client.fetch_available_numbers()
            text = fmt_numbers(numbers)
            back_btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="menu")]])
            if len(text) > 4000:
                await query.edit_message_text(text[:4000], parse_mode=ParseMode.MARKDOWN, reply_markup=back_btn)
            else:
                await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=back_btn)
        except Exception as e:
            await query.edit_message_text(
                f"❌ Error: {e}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="menu")]]),
            )

    elif data == "monitor_start":
        if monitor_running:
            await query.edit_message_text("✅ Monitor already running.", reply_markup=main_menu_keyboard())
        else:
            monitor_running = True
            monitor_task = asyncio.create_task(monitor_loop(ctx.application))
            await query.edit_message_text(
                f"▶️ *Monitor started!* Polling every {POLL_INTERVAL}s.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=main_menu_keyboard(),
            )

    elif data == "monitor_stop":
        if not monitor_running:
            await query.edit_message_text("⏹ Monitor not running.", reply_markup=main_menu_keyboard())
        else:
            monitor_running = False
            if monitor_task:
                monitor_task.cancel()
            await query.edit_message_text("⏹ *Monitor stopped.*", parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu_keyboard())

    elif data == "refresh_login":
        await query.edit_message_text("🔄 Re-logging into IVASMS…")
        try:
            client = IVASMSClient()
            client.login()
            await query.edit_message_text("✅ Login refreshed.", reply_markup=main_menu_keyboard())
        except Exception as e:
            await query.edit_message_text(f"❌ Login failed: {e}", reply_markup=main_menu_keyboard())

    elif data == "status":
        state = "🟢 Running" if monitor_running else "🔴 Stopped"
        ranges = storage.load()
        await query.edit_message_text(
            f"ℹ️ *Bot Status*\n━━━━━━━━━━━━━━━━━━━━\n"
            f"Monitor: {state}\n"
            f"Cached ranges: `{len(ranges)}`\n"
            f"Poll interval: `{POLL_INTERVAL}s`\n"
            f"Account: `{IVASMS_EMAIL}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="menu")]]),
        )

    elif data == "clear_cache":
        storage.clear()
        await query.edit_message_text("🧹 Cache cleared.", reply_markup=main_menu_keyboard())

    elif data == "custom_date":
        await query.edit_message_text(
            "📅 Use /custom command to enter a date range.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="menu")]]),
        )

    elif data == "menu":
        await query.edit_message_text(
            "🏠 *Main Menu*", parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu_keyboard()
        )


# ═══════════════════════════════════════════════════════════════════════════════
#  MONITOR LOOP
# ═══════════════════════════════════════════════════════════════════════════════

async def monitor_loop(app: Application):
    global monitor_running
    logger.info("Monitor loop started.")
    bot: Bot = app.bot

    today = datetime.now()
    from_date = today.strftime("%m/%d/%Y")
    to_date = (today + timedelta(days=1)).strftime("%m/%d/%Y")

    session_start = time.time()
    client = IVASMSClient()

    try:
        client.login()
        logger.info("Logged in to IVASMS.")
    except Exception as e:
        logger.error(f"Initial login failed: {e}")
        await bot.send_message(chat_id=CHAT_ID, text=f"❌ Monitor login failed: {e}")
        monitor_running = False
        return

    # Bootstrap existing data
    try:
        initial_ranges = client.fetch_statistics(from_date, to_date)
        storage.save(initial_ranges)
        logger.info(f"Loaded {len(initial_ranges)} ranges on startup.")
    except Exception as e:
        logger.warning(f"Could not fetch initial stats: {e}")
        initial_ranges = storage.load()

    existing_dict = {r["range_name"]: r for r in initial_ranges}

    while monitor_running:
        try:
            # Re-login every SESSION_TIMEOUT seconds
            if time.time() - session_start > SESSION_TIMEOUT:
                logger.info("Session timeout — re-logging in.")
                client = IVASMSClient()
                client.login()
                session_start = time.time()
                # Refresh date range at midnight
                today = datetime.now()
                from_date = today.strftime("%m/%d/%Y")
                to_date = (today + timedelta(days=1)).strftime("%m/%d/%Y")

            new_ranges = client.fetch_statistics(from_date, to_date)
            new_dict = {r["range_name"]: r for r in new_ranges}

            for range_data in new_ranges:
                rname = range_data["range_name"]
                cur_count = range_data["count"]
                existing = existing_dict.get(rname)

                if not existing:
                    logger.info(f"New range detected: {rname}")
                    await _process_new_range(client, bot, range_data, to_date)
                elif cur_count > existing["count"]:
                    diff = cur_count - existing["count"]
                    logger.info(f"{rname}: +{diff} SMS ({existing['count']} → {cur_count})")
                    await _process_updated_range(client, bot, range_data, diff, to_date)

            existing_dict = new_dict
            storage.save(new_ranges)

        except asyncio.CancelledError:
            logger.info("Monitor loop cancelled.")
            break
        except Exception as e:
            logger.error(f"Monitor error: {e}")
            try:
                await bot.send_message(chat_id=CHAT_ID, text=f"⚠️ Monitor error: {e}\nRetrying…")
            except Exception:
                pass

        await asyncio.sleep(POLL_INTERVAL)

    logger.info("Monitor loop exited.")


async def _process_new_range(client: "IVASMSClient", bot: Bot, range_data: dict, to_date: str):
    rname = range_data["range_name"]
    try:
        numbers = client.fetch_numbers(to_date, rname)
        for nd in numbers[::-1]:
            await _send_sms_alert(client, bot, nd["number"], rname, to_date)
    except Exception as e:
        logger.error(f"Error processing new range {rname}: {e}")


async def _process_updated_range(client: "IVASMSClient", bot: Bot, range_data: dict, diff: int, to_date: str):
    rname = range_data["range_name"]
    try:
        numbers = client.fetch_numbers(to_date, rname)
        for nd in numbers[-diff:][::-1]:
            await _send_sms_alert(client, bot, nd["number"], rname, to_date)
    except Exception as e:
        logger.error(f"Error processing updated range {rname}: {e}")


async def _send_sms_alert(client: "IVASMSClient", bot: Bot, number: str, range_name: str, to_date: str):
    try:
        msg_data = client.fetch_message(to_date, number, range_name)
        sms = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "number": number,
            "message": msg_data["message"],
            "range": range_name,
            "revenue": msg_data["revenue"],
        }
        storage.save_sms(sms)
        await bot.send_message(
            chat_id=CHAT_ID,
            text=fmt_sms(sms),
            parse_mode=ParseMode.MARKDOWN,
        )
        logger.info(f"SMS alert sent for +{number}")
    except Exception as e:
        logger.error(f"Failed to send alert for {number}: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
#  ERROR HANDLER
# ═══════════════════════════════════════════════════════════════════════════════

async def error_handler(update: object, ctx: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Unhandled exception: {ctx.error}", exc_info=ctx.error)


# ═══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Conversation handler for /custom
    conv = ConversationHandler(
        entry_points=[CommandHandler("custom", cmd_custom)],
        states={
            AWAIT_DATE_FROM: [MessageHandler(filters.TEXT & ~filters.COMMAND, custom_from)],
            AWAIT_DATE_TO: [MessageHandler(filters.TEXT & ~filters.COMMAND, custom_to)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)],
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("ranges", cmd_ranges))
    app.add_handler(CommandHandler("numbers", cmd_numbers))
    app.add_handler(CommandHandler("monitor", cmd_monitor))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("refresh", cmd_refresh))
    app.add_handler(CommandHandler("clearcache", cmd_clearcache))
    app.add_handler(CommandHandler("latest", cmd_latest))
    app.add_handler(CommandHandler("range", cmd_range_detail))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_error_handler(error_handler)

    logger.info("Bot polling started.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
