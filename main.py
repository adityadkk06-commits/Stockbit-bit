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
from multi_screener import (
    screen_bsjp_multi, screen_hybrid_trend, screen_scalping_harian,
    run_auto_screener, get_auto_mode,
    scalping_checklist, bsjp_multi_checklist, hybrid_checklist,
    MultiScanResult,
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

WIB = timezone(timedelta(hours=7))


# ─────────────────────────────────────────
# MARKET HOURS HELPER
# ─────────────────────────────────────────
def market_status() -> tuple[bool, str]:
    now = datetime.now(WIB)
    wd  = now.weekday()
    t   = now.hour * 60 + now.minute

    if wd >= 5:
        return False, f"⚠️ Pasar tutup (hari {['Sen','Sel','Rab','Kam','Jum','Sab','Min'][wd]}). Data menggunakan penutupan terakhir."

    open_min  = 9  * 60
    close_min = 16 * 60 + 30

    if t < open_min:
        return False, "⚠️ Pasar belum buka (buka 09:00 WIB). Data menggunakan penutupan terakhir."
    if t > close_min:
        return False, "⚠️ Pasar sudah tutup (tutup 16:30 WIB). Data menggunakan penutupan terakhir."

    return True, "🟢 Pasar sedang buka"


# ─────────────────────────────────────────
# FORMATTERS — existing screeners
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
        lines.append(
            f"⚠️ *Scanned {sr.total_fetched} saham — tidak ada yang lolos filter.*\n"
        )

        top_reasons = sorted(sr.skip_reasons.items(), key=lambda x: -x[1])[:4]
        if top_reasons:
            lines.append("_Alasan utama gagal filter:_")
            for reason, count in top_reasons:
                lines.append(f"  • {reason}: {count} saham")
            lines.append("")

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

    if not is_open:
        lines.append(f"\n_{mkt_msg}_")

    return "\n".join(lines)


# ─────────────────────────────────────────
# FORMATTERS — multi screener
# ─────────────────────────────────────────
def fmt_bsjp_multi(i: int, r: dict) -> str:
    sign = "+" if r["gain_pct"] >= 0 else ""
    checks = bsjp_multi_checklist(r)
    checklist = "  ".join(f"{c[1][0]}{lbl}" for lbl, c in zip(
        ["EMA", "Vol", "MACD", "Accum"], [(c,) for c in checks]))
    confidence = min(100, max(0, r.get("score", 0)))
    smart_money = min(100, int(r["vol_vs_ma20"] * 20 + max(0, r["macd_hist"] * 500)))
    breakout_prob = min(100, int(r["rsi"] * 0.8 + r["ret5d"] * 3))
    return (
        f"*{i}. {r['ticker']}*\n"
        f"Price  : {int(r['close'])} IDR  ({sign}{r['gain_pct']:.2f}%)\n"
        f"Vol/MA20: {r['vol_vs_ma20']:.2f}x  RSI: {r['rsi']:.1f}  MACD: {r['macd_hist']:+.4f}\n"
        f"Entry  : {int(r['close'])}  TP1: {r['tp']}  SL: {r['sl']}\n"
        f"Smart Money: {smart_money}%  Breakout: {breakout_prob}%  Confidence: {confidence}%\n"
    )


def fmt_hybrid(i: int, r: dict) -> str:
    sign = "+" if r["gain_pct"] >= 0 else ""
    confidence = min(100, max(0, r.get("score", 0)))
    trend_str = min(100, int(r["adx"] * 2))
    cont_prob = min(100, int(r["adx"] + r["vol_vs_ma20"] * 10))
    return (
        f"*{i}. {r['ticker']}*\n"
        f"Price  : {int(r['close'])} IDR  ({sign}{r['gain_pct']:.2f}%)\n"
        f"ADX: {r['adx']:.1f}  ATR: {r['atr']:.0f}  Vol/MA20: {r['vol_vs_ma20']:.2f}x\n"
        f"30d Pos: {r['price_pos30']:.0f}%  1W Ret: {r['ret5d']:+.1f}%\n"
        f"Entry  : {int(r['close'])}  TP1: {r['tp']}  SL: {r['sl']}\n"
        f"Trend Str: {trend_str}%  Continuation: {cont_prob}%  Confidence: {confidence}%\n"
    )


def fmt_scalping(i: int, r: dict) -> str:
    sign = "+" if r["gain_pct"] >= 0 else ""
    confidence = min(100, max(0, r.get("score", 0)))
    momentum = min(100, int(r["gain_pct"] * 6 + r["vol_vs_prev"] * 5))
    scalping_sc = min(100, int(r["vol_vs_ma20"] * 15 + r["vwap_dist_pct"] * 10))
    liquidity = min(100, int(r["volume"] / 1_000_000))
    target = round(r["close"] * 1.03)
    rr = round((target - r["close"]) / max(r["close"] - r["sl"], 1), 1)
    return (
        f"*{i}. {r['ticker']}*\n"
        f"Price  : {int(r['close'])} IDR  ({sign}{r['gain_pct']:.2f}%)\n"
        f"Vol/Prev: {r['vol_vs_prev']:.2f}x  RelVol: {r['vol_vs_ma20']:.2f}x  VWAP+: {r['vwap_dist_pct']:.1f}%\n"
        f"IntraRange: {r['intraday_rng']:.1f}%\n"
        f"Entry  : {int(r['close'])}  Target: {target}  SL: {r['sl']}  R/R: {rr}\n"
        f"Momentum: {momentum}%  Scalping: {scalping_sc}%  Liquidity: {liquidity}%  Conf: {confidence}%\n"
    )


def format_multi_result(title: str, emoji: str, sr: MultiScanResult, fmt_fn) -> str:
    is_open, mkt_msg = market_status()
    lines = [f"{emoji} *{title}*\n"]

    if sr.matched:
        lines.append(
            f"✅ *{len(sr.matched)} saham ditemukan* "
            f"(dari {sr.total_fetched} yang di-scan)\n"
        )
        for i, r in enumerate(sr.matched, 1):
            lines.append(fmt_fn(i, r))
    else:
        lines.append(
            f"⚠️ *Scanned {sr.total_fetched} saham — tidak ada yang lolos filter.*\n"
        )
        top_reasons = sorted(sr.skip_reasons.items(), key=lambda x: -x[1])[:4]
        if top_reasons:
            lines.append("_Alasan utama gagal filter:_")
            for reason, count in top_reasons:
                lines.append(f"  • {reason}: {count} saham")

    if not is_open:
        lines.append(f"\n_{mkt_msg}_")

    return "\n".join(lines)


def format_auto_result(mode_key: str, status_msg: str, sr: MultiScanResult | None) -> str:
    _, mode_label, _ = get_auto_mode()
    lines = [f"🤖 *AUTO SCREENING*\n", f"_{status_msg}_\n"]

    if mode_key == "WEEKEND":
        lines.append("📴 *MARKET CLOSED — Weekend Mode*")
        lines.append("\nGunakan screener manual untuk melihat data terakhir.")
        return "\n".join(lines)

    if mode_key == "SUMMARY" or sr is None:
        lines.append("📋 *SUMMARY MODE*")
        lines.append("\nPasar di luar jam perdagangan.")
        lines.append("Gunakan BSJP atau HYBRID TREND untuk melihat kandidat terkuat.")
        return "\n".join(lines)

    fmt_map = {
        "SCALPING": (fmt_scalping, "⚡ SCALPING HARIAN"),
        "BSJP":     (fmt_bsjp_multi, "📈 BSJP"),
        "HYBRID":   (fmt_hybrid, "📊 HYBRID TREND"),
    }
    fmt_fn, label = fmt_map.get(mode_key, (fmt_scalping, "SCREENER"))

    if sr.matched:
        lines.append(f"✅ *{len(sr.matched)} saham ditemukan via {label}*\n")
        for i, r in enumerate(sr.matched, 1):
            lines.append(fmt_fn(i, r))
    else:
        lines.append(f"⚠️ *{label}: tidak ada saham yang lolos filter saat ini.*")
        top_reasons = sorted(sr.skip_reasons.items(), key=lambda x: -x[1])[:3]
        for reason, count in top_reasons:
            lines.append(f"  • {reason}: {count} saham")

    return "\n".join(lines)


# ─────────────────────────────────────────
# KEYBOARDS
# ─────────────────────────────────────────
def get_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🔥 BIG ACCUMULATION"), KeyboardButton("📈 BSJP")],
            [KeyboardButton("🚀 ARA HUNTER"), KeyboardButton("📊 MULTI SCREENER")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def get_multi_keyboard() -> ReplyKeyboardMarkup:
    _, _, status_msg = get_auto_mode()
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(f"🤖 AUTO SCREENING")],
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
    await update.message.reply_text(
        f"👋 *IHSG Stock Screener Bot*\n\n"
        f"Status: {mkt_msg}\n"
        f"Universe: *{len(STOCK_UNIVERSE)} saham* IDX\n\n"
        "Pilih screener:\n"
        "🔥 *BIG ACCUMULATION* — Saham murah + akumulasi kuat\n"
        "📈 *BSJP* — Momentum bullish + likuiditas tinggi\n"
        "🚀 *ARA HUNTER* — Potensi Auto Reject Atas\n"
        "📊 *MULTI SCREENER* — BSJP / Hybrid / Scalping / AUTO\n\n"
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
        "📊 *MULTI SCREENER*\n"
        "• *AUTO* — Otomatis pilih screener sesuai jam WIB\n"
        "• *BSJP* — Smart money accumulation (RSI, MACD, BB)\n"
        "• *HYBRID TREND* — Akumulasi + trend breakout (ADX, ATR)\n"
        "• *SCALPING* — Intraday momentum (VWAP, Vol surge)\n\n"
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
# SCREENER RUNNERS
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


# ─────────────────────────────────────────
# MULTI SCREENER HANDLERS
# ─────────────────────────────────────────
async def multi_screener_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, _, status_msg = get_auto_mode()
    await update.message.reply_text(
        f"📊 *MULTI SCREENER*\n\n"
        f"Status Auto: _{status_msg}_\n\n"
        "Pilih mode screener:\n\n"
        "🤖 *AUTO SCREENING* — Otomatis sesuai jam WIB\n"
        "  09:15–11:00 → ⚡ Scalping Harian\n"
        "  11:00–13:00 → 📈 BSJP\n"
        "  13:00–Tutup → 📊 Hybrid Trend\n\n"
        "📈 *MS:BSJP* — Smart Money Accumulation\n"
        "📊 *MS:HYBRID TREND* — Early Trend + Akumulasi\n"
        "⚡ *MS:SCALPING HARIAN* — Intraday Momentum\n\n"
        "_Pilih tombol di bawah:_",
        parse_mode="Markdown",
        reply_markup=get_multi_keyboard(),
    )


async def auto_screening_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, _, status_msg = get_auto_mode()
    msg = await update.message.reply_text(
        f"🤖 *AUTO SCREENING*\n_{status_msg}_\n\n⏳ Menjalankan screener otomatis …",
        parse_mode="Markdown",
    )
    try:
        loop = asyncio.get_event_loop()
        mode_key, status, sr = await loop.run_in_executor(None, run_auto_screener)
        text = format_auto_result(mode_key, status, sr)
    except Exception as e:
        logger.error(f"auto_screening_handler error: {e}", exc_info=True)
        text = "❌ Terjadi kesalahan saat auto screening. Silakan coba lagi."
    await msg.edit_text(text, parse_mode="Markdown", reply_markup=get_multi_keyboard())


async def ms_bsjp_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = await update.message.reply_text(
        f"⏳ Scanning *{len(STOCK_UNIVERSE)} saham* untuk BSJP (Smart Money) …",
        parse_mode="Markdown",
    )
    try:
        loop = asyncio.get_event_loop()
        sr   = await loop.run_in_executor(None, screen_bsjp_multi)
        text = format_multi_result("BSJP — Smart Money Accumulation", "📈", sr, fmt_bsjp_multi)
    except Exception as e:
        logger.error(f"ms_bsjp_handler error: {e}", exc_info=True)
        text = "❌ Terjadi kesalahan saat scan BSJP. Silakan coba lagi."
    await msg.edit_text(text, parse_mode="Markdown", reply_markup=get_multi_keyboard())


async def ms_hybrid_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = await update.message.reply_text(
        f"⏳ Scanning *{len(STOCK_UNIVERSE)} saham* untuk HYBRID TREND …",
        parse_mode="Markdown",
    )
    try:
        loop = asyncio.get_event_loop()
        sr   = await loop.run_in_executor(None, screen_hybrid_trend)
        text = format_multi_result("HYBRID TREND — Early Trend + Akumulasi", "📊", sr, fmt_hybrid)
    except Exception as e:
        logger.error(f"ms_hybrid_handler error: {e}", exc_info=True)
        text = "❌ Terjadi kesalahan saat scan HYBRID TREND. Silakan coba lagi."
    await msg.edit_text(text, parse_mode="Markdown", reply_markup=get_multi_keyboard())


async def ms_scalping_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = await update.message.reply_text(
        f"⏳ Scanning *{len(STOCK_UNIVERSE)} saham* untuk SCALPING HARIAN …",
        parse_mode="Markdown",
    )
    try:
        loop = asyncio.get_event_loop()
        sr   = await loop.run_in_executor(None, screen_scalping_harian)
        text = format_multi_result("SCALPING HARIAN — Intraday Momentum", "⚡", sr, fmt_scalping)
    except Exception as e:
        logger.error(f"ms_scalping_handler error: {e}", exc_info=True)
        text = "❌ Terjadi kesalahan saat scan SCALPING. Silakan coba lagi."
    await msg.edit_text(text, parse_mode="Markdown", reply_markup=get_multi_keyboard())


async def ms_back_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    is_open, mkt_msg = market_status()
    await update.message.reply_text(
        f"🏠 *Menu Utama*\n\nStatus: {mkt_msg}\nUniverse: *{len(STOCK_UNIVERSE)} saham* IDX",
        parse_mode="Markdown",
        reply_markup=get_keyboard(),
    )


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

    # Existing screeners (unchanged)
    app.add_handler(MessageHandler(filters.Regex(r"(?i)BIG ACCUMULATION"), big_accumulation_handler))
    app.add_handler(MessageHandler(filters.Regex(r"(?i)^📈 BSJP$"),        bsjp_handler))
    app.add_handler(MessageHandler(filters.Regex(r"(?i)ARA HUNTER"),        ara_hunter_handler))

    # Multi Screener menu
    app.add_handler(MessageHandler(filters.Regex(r"(?i)MULTI SCREENER"),    multi_screener_menu_handler))

    # Multi Screener sub-options
    app.add_handler(MessageHandler(filters.Regex(r"(?i)AUTO SCREENING"),    auto_screening_handler))
    app.add_handler(MessageHandler(filters.Regex(r"MS:BSJP"),               ms_bsjp_handler))
    app.add_handler(MessageHandler(filters.Regex(r"MS:HYBRID TREND"),       ms_hybrid_handler))
    app.add_handler(MessageHandler(filters.Regex(r"MS:SCALPING HARIAN"),    ms_scalping_handler))
    app.add_handler(MessageHandler(filters.Regex(r"⬅️ KEMBALI"),            ms_back_handler))

    # Fallback
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_handler))

    logger.info(f"Bot started — universe: {len(STOCK_UNIVERSE)} stocks")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
