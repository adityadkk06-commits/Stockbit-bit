import os
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
from telegram.error import Conflict, NetworkError, TimedOut
from config import TELEGRAM_BOT_TOKEN, STOCK_UNIVERSE
from screener import (
    screen_big_accumulation, screen_bsjp, screen_ara_hunter, ScanResult
)
from multi_screener import (
    screen_bsjp_multi, screen_hybrid_trend, screen_scalping_harian,
    run_auto_screener, get_auto_mode,
    MultiScanResult,
    BSJP_FILTERS_MULTI, HYBRID_FILTERS, SCALPING_FILTERS,
)

# ─────────────────────────────────────────
# Logging Setup
# ─────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
for noisy in ("httpx", "httpcore", "telegram", "yfinance",
              "peewee", "urllib3", "asyncio", "requests",
              "apscheduler"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)
WIB = timezone(timedelta(hours=7))

MAX_MSG = 4000   # Telegram safe character limit per message

# Detect Railway environment — Railway sets RAILWAY_ENVIRONMENT automatically
ON_RAILWAY = bool(os.environ.get("RAILWAY_ENVIRONMENT"))


# ─────────────────────────────────────────
# MARKET HOURS HELPER
# ─────────────────────────────────────────
def market_status() -> tuple[bool, str]:
    now = datetime.now(WIB)
    wd  = now.weekday()
    t   = now.hour * 60 + now.minute
    days = ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"]

    if wd >= 5:
        return False, f"⚠️ Pasar tutup (hari {days[wd]}). Data = penutupan terakhir."
    if t < 9 * 60:
        return False, "⚠️ Pasar belum buka (09:00 WIB). Data = penutupan terakhir."
    if t > 16 * 60 + 30:
        return False, "⚠️ Pasar sudah tutup (16:30 WIB). Data = penutupan terakhir."
    return True, "🟢 Pasar sedang buka"


# ─────────────────────────────────────────
# NUMBER FORMATTER
# ─────────────────────────────────────────
def fmt_num(v: float) -> str:
    if v >= 1_000_000_000: return f"{v/1_000_000_000:.1f}B"
    if v >= 1_000_000:     return f"{v/1_000_000:.1f}M"
    if v >= 1_000:         return f"{v/1_000:.1f}K"
    return str(int(v))


# ─────────────────────────────────────────
# SEND HELPER — splits messages > 4000 chars
# ─────────────────────────────────────────
async def send_or_edit(msg, text: str, **kwargs):
    chunks = []
    while len(text) > MAX_MSG:
        split_at = text.rfind("\n", 0, MAX_MSG)
        if split_at < 0:
            split_at = MAX_MSG
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    chunks.append(text)

    try:
        await msg.edit_text(chunks[0], **kwargs)
        for chunk in chunks[1:]:
            await msg.reply_text(chunk, **kwargs)
    except Exception as e:
        logger.warning(f"edit_text failed ({e}), sending as reply")
        try:
            await msg.reply_text(chunks[0], **kwargs)
            for chunk in chunks[1:]:
                await msg.reply_text(chunk, **kwargs)
        except Exception as e2:
            logger.error(f"send_or_edit completely failed: {e2}")


# ─────────────────────────────────────────
# FORMATTERS — original screeners
# ─────────────────────────────────────────
def fmt_stock(i: int, r: dict) -> str:
    sign = "+" if r["gain_pct"] >= 0 else ""
    return (
        f"*{i}. {r['ticker']}*\n"
        f"Price: {int(r['close'])}  Gain: {sign}{r['gain_pct']:.2f}%\n"
        f"Vol: {fmt_num(r['volume'])}  Val: {fmt_num(r['value'])}\n"
        f"Prob: {r['probability']}%  TP: {r['tp']}  SL: {r['sl']}\n"
    )


def format_scan_result(title: str, emoji: str, sr: ScanResult) -> str:
    is_open, mkt_msg = market_status()
    lines = [f"{emoji} *{title}*\n"]

    if sr.matched:
        lines.append(f"✅ *{len(sr.matched)} saham* dari {sr.total_fetched} di-scan\n")
        for i, r in enumerate(sr.matched, 1):
            lines.append(fmt_stock(i, r))
    else:
        lines.append(f"⚠️ Scanned {sr.total_fetched} saham — 0 lolos filter\n")
        top = sorted(sr.skip_reasons.items(), key=lambda x: -x[1])[:4]
        if top:
            lines.append("_Filter paling ketat:_")
            for reason, count in top:
                lines.append(f"  • {reason}: {count} saham")
        if sr.near_miss:
            lines.append("\n_Kandidat terdekat:_")
            for r in sr.near_miss:
                sign = "+" if r["gain_pct"] >= 0 else ""
                lines.append(
                    f"  • *{r['ticker']}* {int(r['close'])} "
                    f"{sign}{r['gain_pct']:.2f}% Vol:{fmt_num(r['volume'])}"
                )

    if not is_open:
        lines.append(f"\n_{mkt_msg}_")

    return "\n".join(lines)


# ─────────────────────────────────────────
# FORMATTERS — multi screener results
# ─────────────────────────────────────────
def fmt_bsjp_multi(i: int, r: dict) -> str:
    sign = "+" if r["gain_pct"] >= 0 else ""
    conf = min(100, max(0, r.get("score", 0)))
    return (
        f"*{i}. {r['ticker']}*\n"
        f"Price: {int(r['close'])}  ({sign}{r['gain_pct']:.2f}%)\n"
        f"Vol/MA20: {r['vol_vs_ma20']:.2f}x  RSI: {r['rsi']:.1f}  "
        f"MACD: {r['macd_hist']:+.4f}\n"
        f"TP1: {r['tp']}  SL: {r['sl']}  Conf: {conf}%\n"
    )


def fmt_hybrid(i: int, r: dict) -> str:
    sign = "+" if r["gain_pct"] >= 0 else ""
    conf = min(100, max(0, r.get("score", 0)))
    return (
        f"*{i}. {r['ticker']}*\n"
        f"Price: {int(r['close'])}  ({sign}{r['gain_pct']:.2f}%)\n"
        f"ADX: {r['adx']:.1f}  ATR: {r['atr']:.0f}  "
        f"Vol/MA20: {r['vol_vs_ma20']:.2f}x\n"
        f"30d Pos: {r['price_pos30']:.0f}%  1W: {r['ret5d']:+.1f}%  "
        f"Conf: {conf}%\n"
        f"TP: {r['tp']}  SL: {r['sl']}\n"
    )


def fmt_scalping(i: int, r: dict) -> str:
    sign = "+" if r["gain_pct"] >= 0 else ""
    conf = min(100, max(0, r.get("score", 0)))
    target = round(r["close"] * 1.03)
    return (
        f"*{i}. {r['ticker']}*\n"
        f"Price: {int(r['close'])}  ({sign}{r['gain_pct']:.2f}%)\n"
        f"Vol/Prev: {r['vol_vs_prev']:.2f}x  VWAP: {r['vwap_dist_pct']:.1f}%\n"
        f"Range: {r['intraday_rng']:.1f}%  Target: {target}  "
        f"SL: {r['sl']}  Conf: {conf}%\n"
    )


def _build_near_miss_text(sr: MultiScanResult, filter_list: list) -> str:
    n = len(filter_list)
    if not sr.near_miss:
        return "⚠️ Tidak ada kandidat mendekati filter."

    lines = [f"⚠️ *0 saham lolos — Near Miss Top {len(sr.near_miss)}:*\n"]
    for i, r in enumerate(sr.near_miss, 1):
        passed = r.get("pass_count", 0)
        pct    = r.get("pass_pct",   0)
        sign   = "+" if r["gain_pct"] >= 0 else ""
        vol    = r.get("vol_vs_ma20", 0.0)
        rsi    = r.get("rsi", 0.0)
        lines.append(
            f"*{i}. {r['ticker']}* — {pct:.0f}% ({passed}/{n} filter)\n"
            f"   {int(r['close'])} IDR  {sign}{r['gain_pct']:.2f}%  "
            f"Vol/MA20: {vol:.2f}x  RSI: {rsi:.1f}"
        )
    return "\n".join(lines)


def _build_debug_text(sr: MultiScanResult) -> str:
    if not sr.filter_counts:
        return ""
    lines = [
        "\n📊 *Debug — Pass Rate per Filter:*",
        f"Total: {sr.total_fetched}  Valid: {sr.total_valid}  Lolos: {sr.total_passed}\n"
    ]
    for label, count in sr.filter_counts.items():
        pct = int(count / max(sr.total_valid, 1) * 100)
        bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
        safe = label.replace("*", "").replace("_", "").replace("`", "")
        lines.append(f"{safe}: {pct}% {bar}")
    return "\n".join(lines)


def format_multi_result(title: str, emoji: str, sr: MultiScanResult,
                        fmt_fn, filter_list: list) -> str:
    is_open, mkt_msg = market_status()
    lines = [f"{emoji} *{title}*\n"]

    if sr.matched:
        lines.append(f"✅ *{len(sr.matched)} saham* dari {sr.total_fetched} di-scan\n")
        for i, r in enumerate(sr.matched, 1):
            lines.append(fmt_fn(i, r))
    else:
        lines.append(_build_near_miss_text(sr, filter_list))
        debug = _build_debug_text(sr)
        if debug:
            lines.append(debug)

    if not is_open:
        lines.append(f"\n_{mkt_msg}_")

    return "\n".join(lines)


def format_auto_result(mode_key: str, status_msg: str,
                       sr: MultiScanResult | None) -> str:
    lines = [f"🤖 *AUTO SCREENING*\n_{status_msg}_\n"]

    if mode_key == "WEEKEND":
        lines.append("📴 *Market Closed — Weekend*")
        lines.append("_Gunakan screener manual untuk lihat data terakhir._")
        return "\n".join(lines)

    if mode_key == "SUMMARY" or sr is None:
        lines.append("📋 _Pasar di luar jam perdagangan._")
        lines.append("Gunakan BSJP / HYBRID TREND untuk lihat kandidat terkuat.")
        return "\n".join(lines)

    fmt_map = {
        "SCALPING": (fmt_scalping,    "⚡ SCALPING HARIAN",        SCALPING_FILTERS),
        "BSJP":     (fmt_bsjp_multi,  "📈 BSJP Smart Money",       BSJP_FILTERS_MULTI),
        "HYBRID":   (fmt_hybrid,      "📊 HYBRID TREND",           HYBRID_FILTERS),
    }
    fmt_fn, label, fl = fmt_map.get(mode_key, (fmt_scalping, "SCREENER", SCALPING_FILTERS))

    if sr.matched:
        lines.append(f"✅ *{len(sr.matched)} saham via {label}*\n")
        for i, r in enumerate(sr.matched, 1):
            lines.append(fmt_fn(i, r))
    else:
        lines.append(_build_near_miss_text(sr, fl))
        debug = _build_debug_text(sr)
        if debug:
            lines.append(debug)

    return "\n".join(lines)


# ─────────────────────────────────────────
# KEYBOARDS
# ─────────────────────────────────────────
def get_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🔥 BIG ACCUMULATION"), KeyboardButton("📈 BSJP")],
            [KeyboardButton("🚀 ARA HUNTER"),       KeyboardButton("📊 MULTI SCREENER")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def get_multi_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🤖 AUTO SCREENING")],
            [KeyboardButton("📈 MS:BSJP"), KeyboardButton("📊 MS:HYBRID TREND")],
            [KeyboardButton("⚡ MS:SCALPING HARIAN")],
            [KeyboardButton("⬅️ KEMBALI")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


# ─────────────────────────────────────────
# COMMAND HANDLERS
# ─────────────────────────────────────────
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    is_open, mkt_msg = market_status()
    _, _, auto_status = get_auto_mode()
    env_label = "Railway ☁️" if ON_RAILWAY else "Replit 🔧"
    await update.message.reply_text(
        f"👋 *From Zero To Billiuner — IDX Screener*\n\n"
        f"Status: {mkt_msg}\n"
        f"Auto Mode: {auto_status}\n"
        f"Universe: *{len(STOCK_UNIVERSE)} saham* IDX\n"
        f"Env: {env_label}\n\n"
        "Pilih screener dari tombol di bawah 👇",
        parse_mode="Markdown",
        reply_markup=get_keyboard(),
    )


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📖 *Panduan Screener IDX*\n\n"
        "🔥 *BIG ACCUMULATION* — Saham < 500, A/D kuat, vol surge\n"
        "📈 *BSJP* — Vol > 2x MA20, gain > 1%, MA20 > MA50\n"
        "🚀 *ARA HUNTER* — Gain > 5%, close > open, above MA5\n\n"
        "📊 *MULTI SCREENER*\n"
        "• 🤖 AUTO — Otomatis sesuai jam WIB\n"
        "  09:15–11:00 = ⚡ Scalping\n"
        "  11:00–13:00 = 📈 BSJP\n"
        "  13:00–16:30 = 📊 Hybrid\n"
        "• MS:BSJP — RSI 45-70, MACD, Vol > 1.5x MA20\n"
        "• MS:HYBRID — ADX > 20, vol inc 3hr, MA20 > MA50\n"
        "• MS:SCALPING — Vol > 10M, gain 3-15%, VWAP +1%\n\n"
        "_Jika 0 saham lolos → tampil Near Miss + Debug_\n"
        "TP = +5%  |  SL = -3%",
        parse_mode="Markdown",
        reply_markup=get_keyboard(),
    )


# ─────────────────────────────────────────
# ASYNC RUNNER
# ─────────────────────────────────────────
async def _run_async(fn):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, fn)


# ─────────────────────────────────────────
# ORIGINAL SCREENER HANDLERS
# ─────────────────────────────────────────
async def big_accumulation_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = await update.message.reply_text(
        f"⏳ Scanning *{len(STOCK_UNIVERSE)} saham* untuk BIG ACCUMULATION …",
        parse_mode="Markdown",
    )
    try:
        sr   = await _run_async(screen_big_accumulation)
        text = format_scan_result("BIG ACCUMULATION", "🔥", sr)
    except Exception as e:
        logger.error(f"big_accumulation_handler: {e}", exc_info=True)
        text = "❌ Error saat scan BIG ACCUMULATION. Coba lagi."
    await send_or_edit(msg, text, parse_mode="Markdown")


async def bsjp_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = await update.message.reply_text(
        f"⏳ Scanning *{len(STOCK_UNIVERSE)} saham* untuk BSJP …",
        parse_mode="Markdown",
    )
    try:
        sr   = await _run_async(screen_bsjp)
        text = format_scan_result("BSJP", "📈", sr)
    except Exception as e:
        logger.error(f"bsjp_handler: {e}", exc_info=True)
        text = "❌ Error saat scan BSJP. Coba lagi."
    await send_or_edit(msg, text, parse_mode="Markdown")


async def ara_hunter_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = await update.message.reply_text(
        f"⏳ Scanning *{len(STOCK_UNIVERSE)} saham* untuk ARA HUNTER …",
        parse_mode="Markdown",
    )
    try:
        sr   = await _run_async(screen_ara_hunter)
        text = format_scan_result("ARA HUNTER", "🚀", sr)
    except Exception as e:
        logger.error(f"ara_hunter_handler: {e}", exc_info=True)
        text = "❌ Error saat scan ARA HUNTER. Coba lagi."
    await send_or_edit(msg, text, parse_mode="Markdown")


# ─────────────────────────────────────────
# MULTI SCREENER HANDLERS
# ─────────────────────────────────────────
async def multi_screener_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, _, auto_status = get_auto_mode()
    await update.message.reply_text(
        f"📊 *MULTI SCREENER*\n\n"
        f"Auto Status: _{auto_status}_\n\n"
        "🤖 *AUTO* — Pilih screener otomatis sesuai jam WIB\n"
        "  09:15–11:00 → ⚡ Scalping Harian\n"
        "  11:00–13:00 → 📈 BSJP Smart Money\n"
        "  13:00–16:30 → 📊 Hybrid Trend\n\n"
        "📈 *MS:BSJP* — Smart Money Accumulation\n"
        "📊 *MS:HYBRID TREND* — Early Trend + Akumulasi\n"
        "⚡ *MS:SCALPING HARIAN* — Intraday Momentum\n",
        parse_mode="Markdown",
        reply_markup=get_multi_keyboard(),
    )


async def auto_screening_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, _, status = get_auto_mode()
    msg = await update.message.reply_text(
        f"🤖 *AUTO SCREENING*\n_{status}_\n\n⏳ Menjalankan screener otomatis …",
        parse_mode="Markdown",
    )
    try:
        loop = asyncio.get_event_loop()
        mode_key, status2, sr = await loop.run_in_executor(None, run_auto_screener)
        text = format_auto_result(mode_key, status2, sr)
    except Exception as e:
        logger.error(f"auto_screening_handler: {e}", exc_info=True)
        text = "❌ Error saat auto screening. Coba lagi."
    await send_or_edit(msg, text, parse_mode="Markdown", reply_markup=get_multi_keyboard())


async def ms_bsjp_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = await update.message.reply_text(
        f"⏳ Scanning *{len(STOCK_UNIVERSE)} saham* untuk BSJP Smart Money …",
        parse_mode="Markdown",
    )
    try:
        loop = asyncio.get_event_loop()
        sr   = await loop.run_in_executor(None, screen_bsjp_multi)
        text = format_multi_result(
            "BSJP — Smart Money Accumulation", "📈",
            sr, fmt_bsjp_multi, BSJP_FILTERS_MULTI
        )
    except Exception as e:
        logger.error(f"ms_bsjp_handler: {e}", exc_info=True)
        text = "❌ Error saat scan MS:BSJP. Coba lagi."
    await send_or_edit(msg, text, parse_mode="Markdown", reply_markup=get_multi_keyboard())


async def ms_hybrid_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = await update.message.reply_text(
        f"⏳ Scanning *{len(STOCK_UNIVERSE)} saham* untuk HYBRID TREND …",
        parse_mode="Markdown",
    )
    try:
        loop = asyncio.get_event_loop()
        sr   = await loop.run_in_executor(None, screen_hybrid_trend)
        text = format_multi_result(
            "HYBRID TREND — Early Trend + Akumulasi", "📊",
            sr, fmt_hybrid, HYBRID_FILTERS
        )
    except Exception as e:
        logger.error(f"ms_hybrid_handler: {e}", exc_info=True)
        text = "❌ Error saat scan MS:HYBRID. Coba lagi."
    await send_or_edit(msg, text, parse_mode="Markdown", reply_markup=get_multi_keyboard())


async def ms_scalping_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = await update.message.reply_text(
        f"⏳ Scanning *{len(STOCK_UNIVERSE)} saham* untuk SCALPING HARIAN …",
        parse_mode="Markdown",
    )
    try:
        loop = asyncio.get_event_loop()
        sr   = await loop.run_in_executor(None, screen_scalping_harian)
        text = format_multi_result(
            "SCALPING HARIAN — Intraday Momentum", "⚡",
            sr, fmt_scalping, SCALPING_FILTERS
        )
    except Exception as e:
        logger.error(f"ms_scalping_handler: {e}", exc_info=True)
        text = "❌ Error saat scan MS:SCALPING. Coba lagi."
    await send_or_edit(msg, text, parse_mode="Markdown", reply_markup=get_multi_keyboard())


async def ms_back_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    is_open, mkt_msg = market_status()
    await update.message.reply_text(
        f"🏠 *Menu Utama*\n\n{mkt_msg}\nUniverse: *{len(STOCK_UNIVERSE)} saham* IDX",
        parse_mode="Markdown",
        reply_markup=get_keyboard(),
    )


async def unknown_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Pilih screener dari tombol di bawah 👇",
        reply_markup=get_keyboard(),
    )


# ─────────────────────────────────────────
# ERROR HANDLER
# ─────────────────────────────────────────
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err = context.error
    if isinstance(err, Conflict):
        logger.warning("Conflict: another bot instance is active. Retrying after delay…")
        await asyncio.sleep(5)
        return
    if isinstance(err, (NetworkError, TimedOut)):
        logger.warning(f"Network issue (will retry): {err}")
        return
    logger.error(f"Unhandled error: {err}", exc_info=err)


# ─────────────────────────────────────────
# BUILD APP
# ─────────────────────────────────────────
def build_app() -> Application:
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN is not set.")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_error_handler(error_handler)

    # Original screeners
    app.add_handler(MessageHandler(filters.Regex(r"BIG ACCUMULATION"),  big_accumulation_handler))
    app.add_handler(MessageHandler(filters.Regex(r"^📈 BSJP$"),          bsjp_handler))
    app.add_handler(MessageHandler(filters.Regex(r"ARA HUNTER"),         ara_hunter_handler))

    # Multi screener sub-options (specific first)
    app.add_handler(MessageHandler(filters.Regex(r"MS:BSJP"),            ms_bsjp_handler))
    app.add_handler(MessageHandler(filters.Regex(r"MS:HYBRID TREND"),    ms_hybrid_handler))
    app.add_handler(MessageHandler(filters.Regex(r"MS:SCALPING"),        ms_scalping_handler))
    app.add_handler(MessageHandler(filters.Regex(r"AUTO SCREENING"),     auto_screening_handler))
    app.add_handler(MessageHandler(filters.Regex(r"KEMBALI"),            ms_back_handler))
    app.add_handler(MessageHandler(filters.Regex(r"MULTI SCREENER"),     multi_screener_menu_handler))

    # Commands
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("help",  help_handler))

    # Fallback
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_handler))

    return app


# ─────────────────────────────────────────
# ENTRY POINT — webhook on Railway, polling elsewhere
# ─────────────────────────────────────────
def main() -> None:
    app = build_app()

    # Railway: use webhook mode to avoid Telegram polling conflicts
    webhook_url = os.environ.get("WEBHOOK_URL", "")
    port        = int(os.environ.get("PORT", 8080))

    if ON_RAILWAY and webhook_url:
        logger.info(f"Starting in WEBHOOK mode — {webhook_url}")
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path="/webhook",
            webhook_url=f"{webhook_url.rstrip('/')}/webhook",
        )
    else:
        env = "Railway (no WEBHOOK_URL set)" if ON_RAILWAY else "Replit/local"
        logger.info(f"Bot started in POLLING mode [{env}] — universe: {len(STOCK_UNIVERSE)} stocks")
        app.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )


if __name__ == "__main__":
    main()
