import logging
import asyncio
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from config import TELEGRAM_BOT_TOKEN, STOCK_UNIVERSE
from screener import screen_big_accumulation, screen_bsjp, screen_ara_hunter

# ─────────────────────────────────────────
# Logging Setup
# ─────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────
def format_number(value: float) -> str:
    """Convert large numbers to human-readable format (M/B)."""
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B"
    elif value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    elif value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return str(int(value))


def format_results(title: str, emoji: str, results: list[dict]) -> str:
    """Format a list of screener results into a clean Telegram message."""
    if not results:
        return f"{emoji} *{title}*\n\nNo stocks matched the filter criteria right now. Try again later."

    lines = [f"{emoji} *{title}*\n"]
    for i, r in enumerate(results, 1):
        gain_sign = "+" if r["gain_pct"] >= 0 else ""
        lines.append(
            f"*{i}. {r['ticker']}*\n"
            f"Price      : {int(r['close'])}\n"
            f"Gain       : {gain_sign}{r['gain_pct']:.2f}%\n"
            f"Volume     : {format_number(r['volume'])}\n"
            f"Value      : {format_number(r['value'])}\n"
            f"Probability: {r['probability']}%\n"
            f"TP         : {r['tp']}\n"
            f"SL         : {r['sl']}\n"
        )
    return "\n".join(lines)


# ─────────────────────────────────────────
# MAIN MENU KEYBOARD
# ─────────────────────────────────────────
def get_main_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton("🔥 BIG ACCUMULATION"), KeyboardButton("📈 BSJP")],
        [KeyboardButton("🚀 ARA HUNTER")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)


# ─────────────────────────────────────────
# COMMAND HANDLERS
# ─────────────────────────────────────────
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start — show welcome message and menu."""
    await update.message.reply_text(
        "👋 *IHSG Stock Screener Bot*\n\n"
        "Pilih screener yang ingin dijalankan:\n\n"
        "🔥 *BIG ACCUMULATION* — Saham murah dengan akumulasi kuat\n"
        "📈 *BSJP* — Momentum bullish dengan likuiditas tinggi\n"
        "🚀 *ARA HUNTER* — Potensi Auto Reject Atas\n\n"
        "_Tekan tombol di bawah untuk mulai scan._",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(),
    )


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help — describe each screener."""
    await update.message.reply_text(
        "📖 *Panduan Screener*\n\n"
        "🔥 *BIG ACCUMULATION*\n"
        "Mencari saham murah (< 500) dengan akumulasi bandar kuat dan volume surge.\n\n"
        "📈 *BSJP*\n"
        "Mencari saham dengan momentum bullish kuat, likuiditas tinggi, dan foreign net buy.\n\n"
        "🚀 *ARA HUNTER*\n"
        "Mencari saham dengan momentum potensial Auto Reject Atas (batas atas).\n\n"
        "Skor *Probability* dihitung dari:\n"
        "• Volume surge\n"
        "• Momentum harga\n"
        "• Tren Moving Average\n"
        "• Price breakout vs MA5\n\n"
        "TP = Harga saat ini + 5%\n"
        "SL = Harga saat ini - 3%",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(),
    )


# ─────────────────────────────────────────
# SCREENER TRIGGER HANDLERS
# Each handler sends a "Scanning..." message,
# runs the screener in a thread pool, then replies
# ─────────────────────────────────────────
async def run_screener_async(screener_fn, universe):
    """Run a blocking screener function in a background thread."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, screener_fn, universe)


async def big_accumulation_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Triggered when user taps BIG ACCUMULATION button."""
    msg = await update.message.reply_text(
        "⏳ Scanning market for *BIG ACCUMULATION*...",
        parse_mode="Markdown",
    )
    try:
        results = await run_screener_async(screen_big_accumulation, STOCK_UNIVERSE)
        text = format_results("BIG ACCUMULATION", "🔥", results)
    except Exception as e:
        logger.error(f"big_accumulation error: {e}")
        text = "❌ Terjadi kesalahan saat scan. Silakan coba lagi."

    await msg.edit_text(text, parse_mode="Markdown")


async def bsjp_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Triggered when user taps BSJP button."""
    msg = await update.message.reply_text(
        "⏳ Scanning market for *BSJP*...",
        parse_mode="Markdown",
    )
    try:
        results = await run_screener_async(screen_bsjp, STOCK_UNIVERSE)
        text = format_results("BSJP", "📈", results)
    except Exception as e:
        logger.error(f"bsjp error: {e}")
        text = "❌ Terjadi kesalahan saat scan. Silakan coba lagi."

    await msg.edit_text(text, parse_mode="Markdown")


async def ara_hunter_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Triggered when user taps ARA HUNTER button."""
    msg = await update.message.reply_text(
        "⏳ Scanning market for *ARA HUNTER*...",
        parse_mode="Markdown",
    )
    try:
        results = await run_screener_async(screen_ara_hunter, STOCK_UNIVERSE)
        text = format_results("ARA HUNTER", "🚀", results)
    except Exception as e:
        logger.error(f"ara_hunter error: {e}")
        text = "❌ Terjadi kesalahan saat scan. Silakan coba lagi."

    await msg.edit_text(text, parse_mode="Markdown")


async def unknown_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle any unrecognised text — show the menu again."""
    await update.message.reply_text(
        "Pilih screener dari tombol di bawah 👇",
        reply_markup=get_main_keyboard(),
    )


# ─────────────────────────────────────────
# BOT ENTRY POINT
# ─────────────────────────────────────────
def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError(
            "TELEGRAM_BOT_TOKEN is not set. "
            "Add it to your Replit Secrets before running."
        )

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Register command handlers
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("help",  help_handler))

    # Register button (message) handlers — match exact button labels
    app.add_handler(MessageHandler(filters.Regex(r"(?i)BIG ACCUMULATION"), big_accumulation_handler))
    app.add_handler(MessageHandler(filters.Regex(r"(?i)BSJP"),              bsjp_handler))
    app.add_handler(MessageHandler(filters.Regex(r"(?i)ARA HUNTER"),        ara_hunter_handler))

    # Fallback for anything else
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_handler))

    logger.info("Bot is running. Waiting for messages...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
