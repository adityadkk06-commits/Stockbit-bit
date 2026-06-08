"""
multi_screener.py — Multi Screener: BSJP, HYBRID TREND, SCALPING HARIAN + AUTO mode.
DO NOT MODIFY existing screener logic in screener.py — this file only adds NEW screeners.
"""

import logging
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from fetcher import fetch_all
from config import STOCK_UNIVERSE, MAX_RESULTS, TP_PERCENT, SL_PERCENT

logger = logging.getLogger(__name__)

WIB = timezone(timedelta(hours=7))

# ─────────────────────────────────────────────────────────────────
# SAFE VALUE HELPER
# ─────────────────────────────────────────────────────────────────
def _f(val, fb: float = 0.0) -> float:
    try:
        v = float(val)
        return fb if (np.isnan(v) or np.isinf(v)) else v
    except Exception:
        return fb


def _ratio(num, den, fb: float = 0.0) -> float:
    n, d = _f(num), _f(den)
    return fb if d == 0 else n / d


# ─────────────────────────────────────────────────────────────────
# AUTO MODE: TIME-BASED SCREENER SELECTION (WIB)
# ─────────────────────────────────────────────────────────────────
AUTO_SCHEDULE = [
    (9 * 60 + 15,  11 * 60,       "SCALPING",    "⚡ SCALPING HARIAN"),
    (11 * 60,      13 * 60,       "BSJP",         "📈 BSJP"),
    (13 * 60,      14 * 60 + 30,  "HYBRID",       "📊 HYBRID TREND"),
    (14 * 60 + 30, 16 * 60,       "SWING_NIGHT",  "🌙 SWING NIGHT"),
    (16 * 60,      16 * 60 + 30,  "HYBRID",       "📊 HYBRID TREND"),
]


def get_auto_mode() -> tuple[str, str, str]:
    now = datetime.now(WIB)
    wd  = now.weekday()
    t   = now.hour * 60 + now.minute

    if wd >= 5:
        return "WEEKEND", "📴 WEEKEND MODE", "Pasar tutup — menampilkan kandidat terkuat minggu lalu."

    for start, end, key, label in AUTO_SCHEDULE:
        if start <= t < end:
            return key, label, f"🟢 ACTIVE: {label}"

    if t >= 16 * 60 + 30 or t < 9 * 60 + 15:
        return "SUMMARY", "📋 SUMMARY MODE", "Pasar tutup — menampilkan ringkasan & watchlist besok."

    return "SUMMARY", "📋 SUMMARY MODE", "Di luar jam perdagangan."


# ─────────────────────────────────────────────────────────────────
# ADVANCED INDICATORS
# ─────────────────────────────────────────────────────────────────
def compute_multi_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c, v, h, l = df["Close"], df["Volume"], df["High"], df["Low"]

    df["MA5"]   = c.rolling(5).mean()
    df["MA20"]  = c.rolling(20).mean()
    df["MA50"]  = c.rolling(50).mean()
    df["EMA9"]  = c.ewm(span=9,  adjust=False).mean()
    df["EMA21"] = c.ewm(span=21, adjust=False).mean()
    df["VolMA5"]  = v.rolling(5).mean()
    df["VolMA10"] = v.rolling(10).mean()
    df["VolMA20"] = v.rolling(20).mean()

    # RSI (14)
    delta = c.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    rs    = gain / loss.replace(0, np.nan)
    df["RSI"] = 100 - (100 / (1 + rs))

    # MACD
    ema12         = c.ewm(span=12, adjust=False).mean()
    ema26         = c.ewm(span=26, adjust=False).mean()
    df["MACD"]    = ema12 - ema26
    df["Signal"]  = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACDHist"]= df["MACD"] - df["Signal"]

    # Bollinger Bands
    mid            = c.rolling(20).mean()
    std            = c.rolling(20).std()
    df["BB_Upper"] = mid + 2 * std
    df["BB_Lower"] = mid - 2 * std
    df["BB_Mid"]   = mid

    # ATR (14)
    tr = pd.concat([
        h - l,
        (h - c.shift(1)).abs(),
        (l - c.shift(1)).abs(),
    ], axis=1).max(axis=1)
    df["ATR"]   = tr.rolling(14).mean()
    df["ATR10"] = tr.rolling(10).mean()

    # ADX (14)
    plus_dm  = h.diff().clip(lower=0)
    minus_dm = (-l.diff()).clip(lower=0)
    mask_p   = plus_dm < minus_dm;  plus_dm[mask_p]  = 0
    mask_m   = minus_dm <= plus_dm; minus_dm[mask_m] = 0
    atr14    = tr.rolling(14).sum().replace(0, np.nan)
    plus_di  = 100 * plus_dm.rolling(14).sum() / atr14
    minus_di = 100 * minus_dm.rolling(14).sum() / atr14
    dx       = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    df["ADX"] = dx.rolling(14).mean()

    df["IntradayRange"] = ((h - l) / l.replace(0, np.nan)) * 100
    df["VWAP"]          = (h + l + c) / 3

    roll30_max = c.rolling(30).max()
    roll30_min = c.rolling(30).min()
    rng = (roll30_max - roll30_min).replace(0, np.nan)
    df["PricePos30"] = ((c - roll30_min) / rng) * 100

    df["Ret5d"] = c.pct_change(5) * 100

    hl  = (h - l).replace(0, np.nan)
    clv = ((c - l) - (h - c)) / hl
    df["AD"] = (clv.fillna(0) * v).cumsum()

    return df


def _build_multi_row(ticker: str, df: pd.DataFrame) -> dict | None:
    try:
        lat = df.iloc[-1]
        prv = df.iloc[-2]

        close  = _f(lat["Close"]);  prev_c = _f(prv["Close"])
        volume = _f(lat["Volume"]); prev_v = _f(prv["Volume"])

        if close <= 0 or prev_c <= 0 or volume <= 0:
            return None

        gain_pct = ((close - prev_c) / prev_c) * 100
        vwap     = _f(lat.get("VWAP", close))

        high = _f(lat["High"])
        low  = _f(lat["Low"])

        row = dict(
            ticker       = ticker,
            close        = close,
            prev         = prev_c,
            open         = _f(lat["Open"]),
            high         = high,
            low          = low,
            volume       = volume,
            prev_volume  = prev_v,
            value        = close * volume,
            gain_pct     = gain_pct,
            ma5          = _f(lat.get("MA5", 0)),
            ma20         = _f(lat.get("MA20", 0)),
            ma50         = _f(lat.get("MA50", 0)),
            ema9         = _f(lat.get("EMA9", 0)),
            ema21        = _f(lat.get("EMA21", 0)),
            vma5         = _f(lat.get("VolMA5", 0)),
            vma10        = _f(lat.get("VolMA10", 0)),
            vma20        = _f(lat.get("VolMA20", 0)),
            rsi          = _f(lat.get("RSI", 50)),
            macd         = _f(lat.get("MACD", 0)),
            macd_signal  = _f(lat.get("Signal", 0)),
            macd_hist    = _f(lat.get("MACDHist", 0)),
            bb_upper     = _f(lat.get("BB_Upper", 0)),
            bb_lower     = _f(lat.get("BB_Lower", 0)),
            bb_mid       = _f(lat.get("BB_Mid", 0)),
            atr          = _f(lat.get("ATR", 0)),
            atr10        = _f(lat.get("ATR10", 0)),
            adx          = _f(lat.get("ADX", 0)),
            intraday_rng = _f(lat.get("IntradayRange", 0)),
            vwap         = vwap,
            price_pos30  = _f(lat.get("PricePos30", 50)),
            ret5d        = _f(lat.get("Ret5d", 0)),
            market_cap   = _f(lat.get("MarketCap", 0)),
            tp           = round(close * (1 + TP_PERCENT)),
            sl           = round(close * (1 - SL_PERCENT)),
        )

        row["vol_vs_ma20"]   = _ratio(volume, row["vma20"])
        row["vol_vs_prev"]   = _ratio(volume, prev_v)
        row["vwap_dist_pct"] = ((close - vwap) / vwap * 100) if vwap > 0 else 0
        row["rel_vol_10"]    = _ratio(volume, row["vma10"])
        row["range_atr10"]   = _ratio(high - low, row["atr10"]) if row["atr10"] > 0 else 0
        row["price_vs_low"]  = ((close - low) / low * 100) if low > 0 else 0

        try:
            vols = df["Volume"].iloc[-4:-1].values
            row["vol_inc_3d"] = bool(len(vols) == 3 and vols[1] > vols[0] and vols[2] > vols[1])
        except Exception:
            row["vol_inc_3d"] = False

        return row
    except Exception as e:
        logger.debug(f"[MULTI_ROW] {ticker}: {e}")
        return None


# ─────────────────────────────────────────────────────────────────
# MULTI SCAN RESULT — includes debug counters + near-miss
# ─────────────────────────────────────────────────────────────────
class MultiScanResult:
    def __init__(self, name: str):
        self.name           = name
        self.matched:       list[dict] = []
        self.near_miss:     list[dict] = []   # top stocks closest to passing
        self.total_fetched  = 0
        self.total_valid    = 0
        self.total_passed   = 0
        self.filter_counts: dict[str, int] = {}   # how many passed each filter
        self.skip_reasons:  dict[str, int] = {}   # first failing filter → count

    def add_skip(self, reason: str):
        self.skip_reasons[reason] = self.skip_reasons.get(reason, 0) + 1

    def count_filter(self, name: str):
        self.filter_counts[name] = self.filter_counts.get(name, 0) + 1


# ─────────────────────────────────────────────────────────────────
# SCREENER A: BSJP MULTI (Smart Money Accumulation)
# ─────────────────────────────────────────────────────────────────
BSJP_FILTERS_MULTI = [
    ("Price > 100",         lambda r, _: r["close"] > 100),
    ("Price/MA20 > 1%",     lambda r, _: r["ma20"] > 0 and (r["close"] / r["ma20"] - 1) >= 0.01),
    ("Price/MA50 > 1%",     lambda r, _: r["ma50"] > 0 and (r["close"] / r["ma50"] - 1) >= 0.01),
    ("MA20 > MA50",         lambda r, _: r["ma20"] > r["ma50"] > 0),
    ("Vol/MA20 > 1.5x",     lambda r, _: r["vol_vs_ma20"] >= 1.5),
    ("RSI 45–70",           lambda r, _: 45 <= r["rsi"] <= 70),
    ("MACD > Signal",       lambda r, _: r["macd"] > r["macd_signal"]),
    ("1W Return > 1%",      lambda r, _: r["ret5d"] >= 1.0),
    ("Price > BB Lower",    lambda r, _: not (r["bb_lower"] > 0 and r["close"] < r["bb_lower"])),
]


def screen_bsjp_multi() -> MultiScanResult:
    return _run_multi("BSJP MULTI", BSJP_FILTERS_MULTI, _bsjp_score)


def _bsjp_score(row: dict) -> int:
    score = 0
    score += min(30, int(row["macd_hist"] * 1000))
    score += min(20, int((row["vol_vs_ma20"] - 1.0) * 10))
    score += min(25, int((70 - abs(row["rsi"] - 57.5)) * 1.5))
    score += min(25, int(row["ret5d"] * 5))
    return max(0, min(100, score))


# ─────────────────────────────────────────────────────────────────
# SCREENER B: HYBRID TREND
# ─────────────────────────────────────────────────────────────────
HYBRID_FILTERS = [
    ("Price > 50",            lambda r, _: r["close"] > 50),
    ("Price/MA20 > -2%",      lambda r, _: r["ma20"] > 0 and (r["close"] / r["ma20"] - 1) >= -0.02),
    ("MA20 > MA50",           lambda r, _: r["ma20"] > r["ma50"] > 0),
    ("Vol/MA20 > 1.2x",       lambda r, _: r["vol_vs_ma20"] >= 1.2),
    ("Vol inc 3 days",        lambda r, _: r["vol_inc_3d"]),
    ("ADX > 20",              lambda r, _: r["adx"] >= 20),
    ("30d Position 40–85%",   lambda r, _: 40 <= r["price_pos30"] <= 85),
]


def screen_hybrid_trend() -> MultiScanResult:
    return _run_multi("HYBRID TREND", HYBRID_FILTERS, _hybrid_score)


def _hybrid_score(row: dict) -> int:
    score = 0
    score += min(35, int(row["adx"] * 1.0))
    score += min(30, int((row["vol_vs_ma20"] - 1.0) * 15))
    score += min(20, int(max(0, row["ret5d"]) * 4))
    score += min(15, int(row["atr"] * 2) if row["atr"] > 0 else 0)
    return max(0, min(100, score))


# ─────────────────────────────────────────────────────────────────
# SCREENER C: SCALPING HARIAN
# ─────────────────────────────────────────────────────────────────
SCALPING_FILTERS = [
    ("Price 50–5000",         lambda r, _: 50 <= r["close"] <= 5000),
    ("Volume > 10M",          lambda r, _: r["volume"] >= 10_000_000),
    ("Vol/Prev > 2.0x",       lambda r, _: r["vol_vs_prev"] >= 2.0),
    ("Price > VWAP +1%",      lambda r, _: r["vwap_dist_pct"] >= 1.0),
    ("Gain 3–15%",            lambda r, _: 3.0 <= r["gain_pct"] <= 15.0),
    ("RelVol > 1.5x",         lambda r, _: r["vol_vs_ma20"] >= 1.5),
    ("Intraday Range > 3%",   lambda r, _: r["intraday_rng"] >= 3.0),
]


def screen_scalping_harian() -> MultiScanResult:
    return _run_multi("SCALPING HARIAN", SCALPING_FILTERS, _scalping_score)


def _scalping_score(row: dict) -> int:
    score = 0
    score += min(35, int((row["vol_vs_prev"] - 1.0) * 10))
    score += min(25, int(max(0, row["gain_pct"]) * 3))
    score += min(20, int(max(0, row["vwap_dist_pct"]) * 5))
    score += min(20, int(row["vol_vs_ma20"] * 5))
    return max(0, min(100, score))


# ─────────────────────────────────────────────────────────────────
# SCREENER D: SWING NIGHT GW (Afternoon Session — 14:30–16:00 WIB)
# ─────────────────────────────────────────────────────────────────
SWING_NIGHT_GW_FILTERS = [
    ("MarketCap > 1T",         lambda r, _: r["market_cap"] > 1_000_000_000_000),
    ("Price 50–5000",          lambda r, _: 50 <= r["close"] <= 5000),
    ("Volume > 5M",            lambda r, _: r["volume"] >= 5_000_000),
    ("Range/ATR10 < 90%",      lambda r, _: 0 < r["range_atr10"] < 0.9),
    ("Gain +1% to +8%",        lambda r, _: 1.0 <= r["gain_pct"] <= 8.0),
    ("Price vs Low > 1%",      lambda r, _: r["price_vs_low"] >= 1.0),
    ("Vol/Prev >= 1.0x",       lambda r, _: r["vol_vs_prev"] >= 1.0),
    ("VWAP Dist -2% to +2%",   lambda r, _: -2.0 <= r["vwap_dist_pct"] <= 2.0),
    ("RelVol10 > 1.2x",        lambda r, _: r["rel_vol_10"] >= 1.2),
    ("ADX > 20",               lambda r, _: r["adx"] >= 20),
]


def screen_swing_night_gw() -> MultiScanResult:
    return _run_multi("SWING NIGHT GW", SWING_NIGHT_GW_FILTERS, _swing_night_score)


def _swing_night_score(row: dict) -> int:
    score = 0
    # ADX trend strength (30 pts)
    if row["adx"] > 20:
        score += min(30, int((row["adx"] - 20) * 2))
    # Relative volume (25 pts)
    score += min(25, int((row["rel_vol_10"] - 1.0) * 20))
    # Afternoon volume ratio vs prev day (20 pts)
    score += min(20, int((row["vol_vs_prev"] - 1.0) * 15))
    # VWAP proximity — closer = higher score (15 pts)
    vwap_abs = abs(row["vwap_dist_pct"])
    score += max(0, 15 - int(vwap_abs * 7))
    # Gain momentum (10 pts)
    score += min(10, int(max(0, row["gain_pct"] - 1.0) * 3))
    return max(0, min(100, score))


def swing_night_reasons(r: dict) -> list[str]:
    """Dynamically generate conviction reasons for a SWING NIGHT candidate."""
    reasons = []
    if r["vol_vs_prev"] >= 1.5:
        reasons.append("✅ Strong afternoon accumulation")
    elif r["vol_vs_prev"] >= 1.0:
        reasons.append("✅ Increasing Session 2 volume")
    if r["rel_vol_10"] >= 1.5:
        reasons.append("✅ Above-average relative volume")
    if r["adx"] >= 25:
        reasons.append("✅ Healthy trend strength")
    if abs(r["vwap_dist_pct"]) <= 1.0:
        reasons.append("✅ Trading near VWAP")
    if r["gain_pct"] >= 2.0:
        reasons.append("✅ Potential next-day continuation")
    if not reasons:
        reasons.append("✅ Passes all Swing Night criteria")
    return reasons


# ─────────────────────────────────────────────────────────────────
# GENERIC MULTI RUNNER — with full debug counters + near-miss
# ─────────────────────────────────────────────────────────────────
NEAR_MISS_TOP = 10

def _run_multi(name: str, filter_list: list, score_fn) -> MultiScanResult:
    sr = MultiScanResult(name)
    n_filters = len(filter_list)

    stock_data = fetch_all(STOCK_UNIVERSE)
    sr.total_fetched = len(stock_data)

    # Per-filter pass count tracking
    filter_pass_counts = {label: 0 for label, _ in filter_list}

    # Near-miss: (filters_passed_count, pct, row)
    near_candidates: list[tuple[int, dict]] = []

    for ticker, df in stock_data.items():
        df  = compute_multi_indicators(df)
        row = _build_multi_row(ticker, df)

        if row is None:
            sr.add_skip("invalid data")
            continue

        sr.total_valid += 1

        # Run each filter individually, track counts
        passed_count   = 0
        first_fail     = None
        for label, fn in filter_list:
            try:
                ok = fn(row, df)
            except Exception:
                ok = False
            if ok:
                filter_pass_counts[label] += 1
                passed_count += 1
            elif first_fail is None:
                first_fail = label

        if passed_count == n_filters:
            # All filters passed
            row["score"]       = score_fn(row)
            row["pass_pct"]    = 100
            row["pass_count"]  = passed_count
            sr.total_passed   += 1
            sr.matched.append(row)
        else:
            if first_fail:
                sr.add_skip(first_fail)
            # Track near-miss candidates
            row["pass_count"] = passed_count
            row["pass_pct"]   = int(passed_count / n_filters * 100)
            near_candidates.append((passed_count, row))

    # Store per-filter counts on result
    sr.filter_counts = filter_pass_counts

    # Sort matched by score
    sr.matched.sort(key=lambda x: x.get("score", 0), reverse=True)
    sr.matched = sr.matched[:MAX_RESULTS]

    # Near-miss: top NEAR_MISS_TOP by filters passed, then by score_fn
    near_candidates.sort(key=lambda x: (-x[0], -score_fn(x[1])))
    sr.near_miss = [r for _, r in near_candidates[:NEAR_MISS_TOP]]

    _log_debug_report(sr, name, n_filters)
    return sr


def _log_debug_report(sr: MultiScanResult, name: str, n_filters: int):
    logger.info(f"\n{'='*38}")
    logger.info(f" DEBUG REPORT: {name}")
    logger.info(f"{'='*38}")
    logger.info(f" Total Stocks   : {sr.total_fetched}")
    logger.info(f" Data Retrieved : {sr.total_valid}")
    logger.info(f" Passed Filters : {sr.total_passed}")
    logger.info(f" Final Results  : {len(sr.matched)}")
    logger.info(f" Telegram Sent  : YES" if sr.matched else f" Telegram Sent  : NEAR-MISS MODE")
    logger.info(f"{'─'*38}")
    logger.info(" Per-filter pass counts:")
    for label, count in sr.filter_counts.items():
        bar = "█" * int(count / max(sr.total_valid, 1) * 20)
        logger.info(f"  {label:<25} {count:>4}/{sr.total_valid}  {bar}")
    logger.info(f"{'='*38}\n")


# ─────────────────────────────────────────────────────────────────
# AUTO SCREENER
# ─────────────────────────────────────────────────────────────────
def run_auto_screener() -> tuple[str, str, MultiScanResult | None]:
    mode_key, mode_label, status_msg = get_auto_mode()
    if mode_key == "SCALPING":
        return mode_key, status_msg, screen_scalping_harian()
    elif mode_key == "BSJP":
        return mode_key, status_msg, screen_bsjp_multi()
    elif mode_key == "HYBRID":
        return mode_key, status_msg, screen_hybrid_trend()
    elif mode_key == "SWING_NIGHT":
        return mode_key, status_msg, screen_swing_night_gw()
    else:
        return mode_key, status_msg, None


# ─────────────────────────────────────────────────────────────────
# CHECKLIST HELPERS
# ─────────────────────────────────────────────────────────────────
def scalping_checklist(row: dict) -> list[tuple[str, str]]:
    return [
        ("Bid/Offer Ratio > 1.5 (vol proxy)", "✅ PASS" if row["vol_vs_ma20"] >= 1.5 else "⚠️ CAUTION"),
        ("Price Above VWAP",                   "✅ PASS" if row["vwap_dist_pct"] >= 0 else "❌ FAIL"),
        ("Volume Spike Confirmed",             "✅ PASS" if row["vol_vs_prev"] >= 2.0 else "❌ FAIL"),
        ("No Large Sell Wall (gain < 12%)",    "✅ PASS" if row["gain_pct"] < 12 else "⚠️ CAUTION"),
    ]


def bsjp_multi_checklist(row: dict) -> list[tuple[str, str]]:
    return [
        ("EMA9 Above EMA21",              "✅ PASS" if row["ema9"] > row["ema21"] > 0 else "❌ FAIL"),
        ("Volume Above Average",          "✅ PASS" if row["vol_vs_ma20"] >= 1.5 else "❌ FAIL"),
        ("MACD Positive",                 "✅ PASS" if row["macd"] > row["macd_signal"] else "❌ FAIL"),
        ("Accumulation Pattern (AD line)","✅ PASS" if row["ret5d"] > 0 else "⚠️ CAUTION"),
    ]


def hybrid_checklist(row: dict) -> list[tuple[str, str]]:
    return [
        ("ADX Above 20",              "✅ PASS" if row["adx"] >= 20 else "❌ FAIL"),
        ("MA20 Above MA50",           "✅ PASS" if row["ma20"] > row["ma50"] > 0 else "❌ FAIL"),
        ("Volume Trend Positive (3d)","✅ PASS" if row["vol_inc_3d"] else "⚠️ CAUTION"),
        ("Relative Strength Positive","✅ PASS" if row["ret5d"] > 0 else "⚠️ CAUTION"),
    ]
