import logging
import asyncio
from datetime import datetime, timezone, timedelta
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from config import TELEGRAM_BOT_TOKEN, STOCK_UNIVERSE
from screener import (
    screen_big_accumulation, screen_bsjp, screen_ara_hunter, ScanResult
)

# ─────────────────────────────────────────
# Logging Setup
# ─────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.DEBUG,
)
for noisy in ("httpx", "httpcore", "telegram", "yfinance",
              "peewee", "urllib3", "asyncio", "requests"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# Jakarta timezone (WIB = UTC+7)
WIB = timezone(timedelta(hours=7))


# ─────────────────────────────────────────
# MARKET HOURS HELPER
# IDX: Mon–Fri  09:00–16:30 WIB
# ─────────────────────────────────────────
def market_status() -> tuple[bool, str]:
    """Return (is_open, status_string)."""
    now = datetime.now(WIB)
    wd  = now.weekday()          # 0=Mon … 6=Sun
    t   = now.hour * 60 + now.minute

    if wd >= 5:
        return False, f"⚠️ Pasar tutup (hari {['Sen','Sel','Rab','Kam','Jum','Sab','Min'][wd]}). Data menggunakan penutupan terakhir."

    open_min  = 9  * 60      # 09:00
    close_min = 16 * 60 + 30 # 16:30

    if t < open_min:
        return False, "⚠️ Pasar belum buka (buka 09:00 WIB). Data menggunakan penutupan terakhir."
    if t > close_min:
        return False, "⚠️ Pasar sudah tutup (tutup 16:30 WIB). Data menggunakan penutupan terakhir."

    return True, "🟢 Pasar sedang buka"


# ─────────────────────────────────────────
# FORMATTERS
# ─────────────────────────────────────────
def fmt_num(value: float) -> str:
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return str(int(value))


def fmt_stock(i: int, r: dict) -> str:
    sign = "+" if r["gain_pct"] >= 0 else ""
    return (
        f"*{i}. {r['ticker']}*\n"
        f"Price      : {int(r['close'])}\n"
        f"Gain       : {sign}{r['gain_pct']:.2f}%\n"
        f"Volume     : {fmt_num(r['volume'])}\n"
        f"Value      : {fmt_num(r['value'])}\n"
        f"Probability: {r['probability']}%\n"
        f"TP         : {r['tp']}\n"
        f"SL         : {r['sl']}\n"
    )


def format_scan_result(title: str, emoji: str, sr: ScanResult) -> str:
    is_open, mkt_msg = market_status()
    lines = [f"{emoji} *{title}*\n"]

    if sr.matched:
        lines.append(
            f"✅ *{len(sr.matched)} saham ditemukan* "
            f"(dari {sr.total_fetched} yang di-scan)\n"
        )
        for i, r in enumerate(sr.matched, 1):
            lines.append(fmt_stock(i, r))
    else:
        # ── No exact matches — show stats + near-miss ──
        lines.append(
            f"⚠️ *Scanned {sr.total_fetched} saham — tidak ada yang lolos filter.*\n"
        )

        # Top skip reasons
        top_reasons = sorted(sr.skip_reasons.items(), key=lambda x: -x[1])[:4]
        if top_reasons:
            lines.append("_Alasan utama gagal filter:_")
            for reason, count in top_reasons:
                lines.append(f"  • {reason}: {count} saham")
            lines.append("")

        # Near-miss candidates
        if sr.near_miss:
            lines.append("_Kandidat terdekat (hampir lolos):_")
            for r in sr.near_miss:
                sign = "+" if r["gain_pct"] >= 0 else ""
                lines.append(
                    f"  • *{r['ticker']}* — "
                    f"{int(r['close'])} IDR  "
                    f"{sign}{r['gain_pct']:.2f}%  "
                    f"Vol {fmt_num(r['volume'])}"
                )
            lines.append("")

    # Market hours note
    if not is_open:
        lines.append(f"\n_{mkt_msg}_")

    return "\n".join(lines)


# ─────────────────────────────────────────
# KEYBOARD
# ─────────────────────────────────────────
def get_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🔥 BIG ACCUMULATION"), KeyboardButton("📈 BSJP")],
            [KeyboardButton("🚀 ARA HUNTER")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


# ─────────────────────────────────────────
# COMMAND HANDLERS
# ─────────────────────────────────────────
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    is_open, mkt_msg = market_status()
    await update.message.reply_text(
        f"👋 *IHSG Stock Screener Bot*\n\n"
        f"Status: {mkt_msg}\n"
        f"Universe: *{len(STOCK_UNIVERSE)} saham* IDX\n\n"
        "Pilih screener:\n"
        "🔥 *BIG ACCUMULATION* — Saham murah + akumulasi kuat\n"
        "📈 *BSJP* — Momentum bullish + likuiditas tinggi\n"
        "🚀 *ARA HUNTER* — Potensi Auto Reject Atas\n\n"
        "_Tekan tombol di bawah untuk mulai scan._",
        parse_mode="Markdown",
        reply_markup=get_keyboard(),
    )


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📖 *Panduan Screener*\n\n"
        "🔥 *BIG ACCUMULATION*\n"
        "Saham < 500 IDR dengan A/D kuat & volume surge (VolMA5 > 1.3× VolMA20)\n\n"
        "📈 *BSJP*\n"
        "Volume hari ini > 2× MA20, gain > 1%, MA20 > MA50, foreign accum\n\n"
        "🚀 *ARA HUNTER*\n"
        "Gain > 5%, close > open, above EMA9, value > 5B IDR\n\n"
        "📊 *Probability Score (0–100):*\n"
        "• Volume surge vs MA20  → maks 30 poin\n"
        "• Momentum harga        → maks 30 poin\n"
        "• EMA/MA trend          → maks 25 poin\n"
        "• Price breakout EMA9   → maks 15 poin\n\n"
        "TP = +5%  |  SL = −3%",
        parse_mode="Markdown",
        reply_markup=get_keyboard(),
    )


# ─────────────────────────────────────────
# SCREENER RUNNERS  (async wrappers)
# ─────────────────────────────────────────
async def _run_async(fn) -> ScanResult:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, fn)


async def big_accumulation_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = await update.message.reply_text(
        f"⏳ Scanning *{len(STOCK_UNIVERSE)} saham* untuk BIG ACCUMULATION …",
        parse_mode="Markdown",
    )
    try:
        sr   = await _run_async(screen_big_accumulation)
        text = format_scan_result("BIG ACCUMULATION", "🔥", sr)
    except Exception as e:
        logger.error(f"big_accumulation_handler error: {e}", exc_info=True)
        text = "❌ Terjadi kesalahan saat scan. Silakan coba lagi."
    await msg.edit_text(text, parse_mode="Markdown")


async def bsjp_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = await update.message.reply_text(
        f"⏳ Scanning *{len(STOCK_UNIVERSE)} saham* untuk BSJP …",
        parse_mode="Markdown",
    )
    try:
        sr   = await _run_async(screen_bsjp)
        text = format_scan_result("BSJP", "📈", sr)
    except Exception as e:
        logger.error(f"bsjp_handler error: {e}", exc_info=True)
        text = "❌ Terjadi kesalahan saat scan. Silakan coba lagi."
    await msg.edit_text(text, parse_mode="Markdown")


async def ara_hunter_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = await update.message.reply_text(
        f"⏳ Scanning *{len(STOCK_UNIVERSE)} saham* untuk ARA HUNTER …",
        parse_mode="Markdown",
    )
    try:
        sr   = await _run_async(screen_ara_hunter)
        text = format_scan_result("ARA HUNTER", "🚀", sr)
    except Exception as e:
        logger.error(f"ara_hunter_handler error: {e}", exc_info=True)
        text = "❌ Terjadi kesalahan saat scan. Silakan coba lagi."
    await msg.edit_text(text, parse_mode="Markdown")


async def unknown_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Pilih screener dari tombol di bawah 👇",
        reply_markup=get_keyboard(),
    )


# ─────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────
def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN is not set in Replit Secrets.")

    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("help",  help_handler))
    app.add_handler(MessageHandler(filters.Regex(r"(?i)BIG ACCUMULATION"), big_accumulation_handler))
    app.add_handler(MessageHandler(filters.Regex(r"(?i)BSJP"),              bsjp_handler))
    app.add_handler(MessageHandler(filters.Regex(r"(?i)ARA HUNTER"),        ara_hunter_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,          unknown_handler))

    logger.info(f"Bot started — universe: {len(STOCK_UNIVERSE)} stocks")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,   # discard stale messages on startup
    )


if __name__ == "__main__":
    main()
