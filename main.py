import os
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
from scanner import scan
from chart import generate_chart, generate_live_chart

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
SCAN_INTERVAL = 300

recent_signals = []


def get_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔍 Check Signal", callback_data="check"),
            InlineKeyboardButton("📈 View Chart", callback_data="chart"),
        ],
        [
            InlineKeyboardButton("🏆 Top Signals", callback_data="topsignals"),
            InlineKeyboardButton("📊 Market Status", callback_data="status"),
        ],
        [
            InlineKeyboardButton("ℹ️ Help", callback_data="help"),
        ]
    ])


def format_signal(signal):
    direction = "BUY" if signal["direction"] == "bullish" else "SELL"
    mode = signal.get("mode", "trend")
    has_fvg = len(signal.get("recent_fvgs", signal.get("fvgs", []))) > 0
    has_ob = len(signal.get("recent_obs", signal.get("obs", []))) > 0
    fvg_quality = signal.get("fvg_quality", "")
    ob_quality = signal.get("ob_quality", "")
    candle_type = signal.get("candle_type", "").replace("_", " ").title()
    m5_details = signal.get("m5_details", [])
    h1_score = signal.get("h1_score", 0)
    m5_score = signal.get("m5_score", 0)

    fvg_line = f"FVG Found ({fvg_quality})" if has_fvg else "FVG Not Detected"
    ob_line = f"Order Block Found ({ob_quality})" if has_ob else "Order Block Not Detected"
    m5_text = "\n".join(m5_details) if m5_details else "M5 Confirmed"

    if mode == "breakout":
        bo_info = signal.get("bo_info", {})
        retest_line = "Retest Confirmed" if bo_info.get("retest") else "No retest yet"
        trend_line = f"BREAKOUT MODE (H1 Neutral)\nEMA200 Break + {retest_line}"
        score_line = f"M5 Score: {m5_score}/100"
    else:
        trend_line = "H1 Trend Confirmed\nEMA Alignment Valid"
        score_line = f"Score: {signal['score']}/100  (H1: {h1_score}  M5: {m5_score})"

    header = "*** BREAKOUT MODE SIGNAL ***" if mode == "breakout" else "XAUUSD SMART MONEY SIGNAL"

    return (
        f"{header}\n\n"
        f"Direction: {direction}\n\n"
        f"Trend:\n"
        f"{trend_line}\n\n"
        f"Detected:\n"
        f"{fvg_line}\n"
        f"{ob_line}\n"
        f"Candle: {candle_type}\n\n"
        f"M5 Analysis:\n"
        f"{m5_text}\n\n"
        f"Entry:\n{signal['entry']}\n\n"
        f"Stop Loss:\n{signal['sl']}\n\n"
        f"Take Profit:\n{signal['tp']}\n\n"
        f"Risk/Reward:\n1 : {signal['rr']}\n\n"
        f"ATR:\n{signal['atr']}\n\n"
        f"Probability Score:\n{score_line}"
    )


async def run_scan_and_reply(message, context):
    thinking = await message.reply_text("Scanning XAUUSD... please wait.")
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, scan)
        signal, reason = result if isinstance(result, tuple) else (result, None)
    except Exception as e:
        logger.error(f"Scan error: {e}", exc_info=True)
        await thinking.edit_text("Error fetching market data. Please try again shortly.")
        return

    await thinking.delete()

    if not signal:
        reason_text = reason or "Conditions not met or probability score below 85/100."
        await message.reply_text(
            f"No signal right now.\n\n"
            f"{reason_text}\n\n"
            f"Auto-scan runs every 5 minutes.",
            reply_markup=get_keyboard()
        )
        return

    recent_signals.append(signal)
    if len(recent_signals) > 10:
        recent_signals.pop(0)

    text = format_signal(signal)

    try:
        loop = asyncio.get_running_loop()
        chart_buf = await loop.run_in_executor(None, generate_chart, signal)
        if chart_buf:
            await message.reply_photo(
                photo=chart_buf,
                caption=text,
                reply_markup=get_keyboard()
            )
            return
    except Exception as e:
        logger.error(f"Chart error: {e}", exc_info=True)

    await message.reply_text(text, reply_markup=get_keyboard())


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if "chat_ids" not in context.bot_data:
        context.bot_data["chat_ids"] = set()
    context.bot_data["chat_ids"].add(chat_id)

    await update.message.reply_text(
        "XAUUSD Smart Money Scanner\n\n"
        "I scan XAUUSD every 5 minutes using:\n"
        "- H1 EMA trend filter (21 / 50 / 200)\n"
        "- M5 Fair Value Gap (FVG) detection\n"
        "- Order Block confirmation\n"
        "- ATR-based dynamic SL/TP (1:3 RR)\n"
        "- Probability scoring — min 85/100 to alert\n\n"
        "Commands:\n"
        "/check — Scan now\n"
        "/topsignals — View recent signals\n"
        "/help — Help",
        reply_markup=get_keyboard()
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "XAUUSD Smart Money Scanner — Help\n\n"
        "/start — Main menu\n"
        "/check — Manual scan now\n"
        "/topsignals — Last 5 signals\n"
        "/help — This message\n\n"
        "Auto-scan runs every 5 minutes.\n"
        "Only signals scoring 85+ are sent.",
        reply_markup=get_keyboard()
    )


async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if "chat_ids" not in context.bot_data:
        context.bot_data["chat_ids"] = set()
    context.bot_data["chat_ids"].add(chat_id)
    await run_scan_and_reply(update.message, context)


async def send_live_chart(message, context):
    from data import get_h1_data, get_m5_data
    from scanner import analyze_trend
    thinking = await message.reply_text("Generating XAUUSD chart... please wait.")
    try:
        loop = asyncio.get_running_loop()
        h1_df = await loop.run_in_executor(None, get_h1_data, 200)
        m5_df = await loop.run_in_executor(None, get_m5_data, 100)
        trend, ema21, ema50, ema200 = analyze_trend(h1_df)
        chart_buf = await loop.run_in_executor(None, generate_live_chart, m5_df, h1_df, trend)
        await thinking.delete()
        if chart_buf:
            price = float(m5_df["Close"].iloc[-1])
            caption = (
                f"XAUUSD M5 Live Chart\n\n"
                f"Price: {price:.2f}\n"
                f"H1 Trend: {trend.upper()}\n"
                f"EMA21: {ema21:.2f}  |  EMA50: {ema50:.2f}  |  EMA200: {ema200:.2f}\n\n"
                f"Blue zones = FVG  |  Green/Red zones = Order Block"
            )
            await message.reply_photo(
                photo=chart_buf,
                caption=caption,
                reply_markup=get_keyboard()
            )
        else:
            await message.reply_text("Could not generate chart. Try again.", reply_markup=get_keyboard())
    except Exception as e:
        logger.error(f"Live chart error: {e}", exc_info=True)
        await thinking.edit_text("Error generating chart. Try again.")


async def chart_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_live_chart(update.message, context)


async def topsignals_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not recent_signals:
        await update.message.reply_text(
            "No signals recorded yet.\nUse /check to scan now.",
            reply_markup=get_keyboard()
        )
        return
    text = f"Last {min(len(recent_signals), 5)} Signals:\n\n"
    for i, sig in enumerate(reversed(recent_signals[-5:]), 1):
        d = "BUY" if sig["direction"] == "bullish" else "SELL"
        text += f"{i}. {d} — Entry: {sig['entry']} | Score: {sig['score']}/100\n"
    await update.message.reply_text(text, reply_markup=get_keyboard())


async def show_status(message, context):
    from data import get_h1_data, get_m5_data
    from scanner import analyze_trend, calc_atr
    thinking = await message.reply_text("Fetching market status...")
    try:
        loop = asyncio.get_running_loop()
        h1_df = await loop.run_in_executor(None, get_h1_data, 200)
        m5_df = await loop.run_in_executor(None, get_m5_data, 100)
        trend, ema21, ema50, ema200 = analyze_trend(h1_df)
        atr = float(calc_atr(m5_df).iloc[-1])
        price = float(m5_df["Close"].iloc[-1])
        trend_label = trend.upper()
        await thinking.edit_text(
            f"XAUUSD Market Status\n\n"
            f"Price: {price:.2f}\n"
            f"H1 Trend: {trend_label}\n"
            f"EMA21: {ema21:.2f}\n"
            f"EMA50: {ema50:.2f}\n"
            f"EMA200: {ema200:.2f}\n"
            f"ATR (M5): {atr:.2f}\n\n"
            f"Auto-scan every 5 min.",
            reply_markup=get_keyboard()
        )
    except Exception as e:
        logger.error(f"Status error: {e}", exc_info=True)
        await thinking.edit_text("Error fetching market data. Try again.")


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "check":
        await run_scan_and_reply(query.message, context)
    elif query.data == "chart":
        await send_live_chart(query.message, context)
    elif query.data == "topsignals":
        if not recent_signals:
            await query.message.reply_text(
                "No signals yet. Use /check to scan.",
                reply_markup=get_keyboard()
            )
            return
        text = f"Last {min(len(recent_signals), 5)} Signals:\n\n"
        for i, sig in enumerate(reversed(recent_signals[-5:]), 1):
            d = "BUY" if sig["direction"] == "bullish" else "SELL"
            text += f"{i}. {d} — Entry: {sig['entry']} | Score: {sig['score']}/100\n"
        await query.message.reply_text(text, reply_markup=get_keyboard())
    elif query.data == "status":
        await show_status(query.message, context)
    elif query.data == "help":
        await query.message.reply_text(
            "XAUUSD Smart Money Scanner — Help\n\n"
            "/start — Main menu\n"
            "/check — Manual scan now\n"
            "/topsignals — Last 5 signals\n"
            "/help — This message\n\n"
            "Auto-scan runs every 5 minutes.\n"
            "Only signals scoring 85+ are sent.",
            reply_markup=get_keyboard()
        )


async def track_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if "chat_ids" not in context.bot_data:
        context.bot_data["chat_ids"] = set()
    context.bot_data["chat_ids"].add(chat_id)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception while handling update:", exc_info=context.error)


async def auto_scan_job(context: ContextTypes.DEFAULT_TYPE):
    logger.info("Auto-scan running...")
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, scan)
        signal, reason = result if isinstance(result, tuple) else (result, None)

        if not signal:
            logger.info(f"Auto-scan: no signal — {reason}")
            return

        recent_signals.append(signal)
        if len(recent_signals) > 10:
            recent_signals.pop(0)

        text = format_signal(signal)
        chat_ids = context.bot_data.get("chat_ids", set())

        chart_buf = None
        try:
            chart_buf = await loop.run_in_executor(None, generate_chart, signal)
        except Exception as e:
            logger.error(f"Chart error in auto-scan: {e}")

        for chat_id in list(chat_ids):
            try:
                if chart_buf:
                    chart_buf.seek(0)
                    await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=chart_buf,
                        caption=text,
                        reply_markup=get_keyboard()
                    )
                else:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        reply_markup=get_keyboard()
                    )
            except Exception as e:
                logger.error(f"Failed to send to {chat_id}: {e}")
    except Exception as e:
        logger.error(f"Auto-scan job error: {e}", exc_info=True)


def main():
    if not TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN is not set!")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("check", check_command))
    app.add_handler(CommandHandler("chart", chart_command))
    app.add_handler(CommandHandler("topsignals", topsignals_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.ALL, track_chat), group=1)
    app.add_error_handler(error_handler)

    app.job_queue.run_repeating(auto_scan_job, interval=SCAN_INTERVAL, first=60)

    logger.info("XAUUSD Smart Money Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
