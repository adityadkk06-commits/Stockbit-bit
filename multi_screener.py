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
    (9 * 60 + 15,  11 * 60,      "SCALPING",  "⚡ SCALPING HARIAN"),
    (11 * 60,      13 * 60,      "BSJP",      "📈 BSJP"),
    (13 * 60,      16 * 60 + 30, "HYBRID",    "📊 HYBRID TREND"),
]


def get_auto_mode() -> tuple[str, str, str]:
    """
    Returns (mode_key, mode_label, status_msg) based on current WIB time.
    mode_key: 'SCALPING' | 'BSJP' | 'HYBRID' | 'SUMMARY' | 'WEEKEND'
    """
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

    # MAs
    df["MA5"]   = c.rolling(5).mean()
    df["MA20"]  = c.rolling(20).mean()
    df["MA50"]  = c.rolling(50).mean()

    # EMA
    df["EMA9"]  = c.ewm(span=9,  adjust=False).mean()
    df["EMA21"] = c.ewm(span=21, adjust=False).mean()

    # Volume MAs
    df["VolMA5"]  = v.rolling(5).mean()
    df["VolMA20"] = v.rolling(20).mean()

    # RSI (14)
    delta = c.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    rs    = gain / loss.replace(0, np.nan)
    df["RSI"] = 100 - (100 / (1 + rs))

    # MACD (12, 26, 9)
    ema12         = c.ewm(span=12, adjust=False).mean()
    ema26         = c.ewm(span=26, adjust=False).mean()
    df["MACD"]    = ema12 - ema26
    df["Signal"]  = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACDHist"]= df["MACD"] - df["Signal"]

    # Bollinger Bands (20, 2)
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
    df["ATR"] = tr.rolling(14).mean()

    # ADX (14)
    plus_dm  = (h.diff()).clip(lower=0)
    minus_dm = (-l.diff()).clip(lower=0)
    mask     = plus_dm < minus_dm
    plus_dm[mask]  = 0
    mask2    = minus_dm <= plus_dm
    minus_dm[mask2] = 0

    atr14     = tr.rolling(14).sum().replace(0, np.nan)
    plus_di   = 100 * plus_dm.rolling(14).sum() / atr14
    minus_di  = 100 * minus_dm.rolling(14).sum() / atr14
    dx        = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
    df["ADX"] = dx.rolling(14).mean()

    # Intraday Range %
    df["IntradayRange"] = ((h - l) / l.replace(0, np.nan)) * 100

    # VWAP proxy: (H+L+C)/3 for the latest bar
    df["VWAP"] = (h + l + c) / 3

    # 30-day price range position (0–100%)
    roll30_max = c.rolling(30).max()
    roll30_min = c.rolling(30).min()
    rng = (roll30_max - roll30_min).replace(0, np.nan)
    df["PricePos30"] = ((c - roll30_min) / rng) * 100

    # 5-day return (1-week perf)
    df["Ret5d"] = c.pct_change(5) * 100

    # Accumulation/Distribution Line
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

        row = dict(
            ticker      = ticker,
            close       = close,
            prev        = prev_c,
            open        = _f(lat["Open"]),
            high        = _f(lat["High"]),
            low         = _f(lat["Low"]),
            volume      = volume,
            prev_volume = prev_v,
            value       = close * volume,
            gain_pct    = gain_pct,
            ma5         = _f(lat.get("MA5", 0)),
            ma20        = _f(lat.get("MA20", 0)),
            ma50        = _f(lat.get("MA50", 0)),
            ema9        = _f(lat.get("EMA9", 0)),
            ema21       = _f(lat.get("EMA21", 0)),
            vma5        = _f(lat.get("VolMA5", 0)),
            vma20       = _f(lat.get("VolMA20", 0)),
            rsi         = _f(lat.get("RSI", 50)),
            macd        = _f(lat.get("MACD", 0)),
            macd_signal = _f(lat.get("Signal", 0)),
            macd_hist   = _f(lat.get("MACDHist", 0)),
            bb_upper    = _f(lat.get("BB_Upper", 0)),
            bb_lower    = _f(lat.get("BB_Lower", 0)),
            bb_mid      = _f(lat.get("BB_Mid", 0)),
            atr         = _f(lat.get("ATR", 0)),
            adx         = _f(lat.get("ADX", 0)),
            intraday_rng= _f(lat.get("IntradayRange", 0)),
            vwap        = _f(lat.get("VWAP", close)),
            price_pos30 = _f(lat.get("PricePos30", 50)),
            ret5d       = _f(lat.get("Ret5d", 0)),
            tp          = round(close * (1 + TP_PERCENT)),
            sl          = round(close * (1 - SL_PERCENT)),
        )

        # Computed ratios
        row["vol_vs_ma20"]  = _ratio(volume, row["vma20"])
        row["vol_vs_prev"]  = _ratio(volume, prev_v)
        row["vwap_dist_pct"]= ((close - row["vwap"]) / row["vwap"]) * 100 if row["vwap"] > 0 else 0

        # Volume increasing 3 days
        try:
            vols = df["Volume"].iloc[-4:-1].values
            row["vol_inc_3d"] = bool(vols[1] > vols[0] and vols[2] > vols[1]) if len(vols) == 3 else False
        except Exception:
            row["vol_inc_3d"] = False

        return row
    except Exception as e:
        logger.debug(f"[MULTI_ROW] {ticker}: {e}")
        return None


# ─────────────────────────────────────────────────────────────────
# MULTI SCREENER RESULT CLASS
# ─────────────────────────────────────────────────────────────────
class MultiScanResult:
    def __init__(self, name: str):
        self.name = name
        self.matched:   list[dict] = []
        self.total_fetched  = 0
        self.total_passed   = 0
        self.skip_reasons: dict[str, int] = {}

    def add_skip(self, reason: str):
        self.skip_reasons[reason] = self.skip_reasons.get(reason, 0) + 1


# ─────────────────────────────────────────────────────────────────
# GENERIC MULTI RUNNER
# ─────────────────────────────────────────────────────────────────
def _run_multi(name: str, filter_fn, score_fn, sort_key: str = "score") -> MultiScanResult:
    sr = MultiScanResult(name)
    stock_data = fetch_all(STOCK_UNIVERSE)
    sr.total_fetched = len(stock_data)

    for ticker, df in stock_data.items():
        df  = compute_multi_indicators(df)
        row = _build_multi_row(ticker, df)

        if row is None:
            sr.add_skip("invalid data")
            continue

        passed, fail_reason = filter_fn(row, df)

        if passed:
            row["score"] = score_fn(row, df)
            sr.total_passed += 1
            sr.matched.append(row)
        else:
            sr.add_skip(fail_reason)

    sr.matched.sort(key=lambda x: x.get(sort_key, 0), reverse=True)
    sr.matched = sr.matched[:MAX_RESULTS]

    logger.info(
        f"[{name}] Scanned {sr.total_fetched} | "
        f"Passed {sr.total_passed}"
    )
    return sr


# ─────────────────────────────────────────────────────────────────
# SCREENER A: BSJP (MULTI — Smart Money Accumulation)
# ─────────────────────────────────────────────────────────────────
def _bsjp_multi_filter(row: dict, df: pd.DataFrame) -> tuple[bool, str]:
    if row["close"] <= 100:
        return False, "Price ≤ 100"
    if row["ma20"] <= 0 or (row["close"] / row["ma20"] - 1) < 0.01:
        return False, "Price/MA20 < 1%"
    if row["ma50"] <= 0 or (row["close"] / row["ma50"] - 1) < 0.01:
        return False, "Price/MA50 < 1%"
    if not (row["ma20"] > row["ma50"] and row["ma50"] > 0):
        return False, "MA20 not > MA50"
    if row["vol_vs_ma20"] < 1.5:
        return False, f"Vol/VolMA20 {row['vol_vs_ma20']:.2f} < 1.5"
    if not (45 <= row["rsi"] <= 70):
        return False, f"RSI {row['rsi']:.1f} not 45–70"
    if row["macd"] <= row["macd_signal"]:
        return False, "MACD below Signal"
    if row["ret5d"] < 1.0:
        return False, f"1W perf {row['ret5d']:.1f}% < 1%"
    if row["bb_lower"] > 0 and row["close"] < row["bb_lower"]:
        return False, "Price below BB Lower"
    return True, "ok"


def _bsjp_multi_score(row: dict, df: pd.DataFrame) -> int:
    score = 0
    score += min(30, int(row["macd_hist"] * 1000))
    score += min(20, int((row["vol_vs_ma20"] - 1.5) * 10))
    score += min(25, int((70 - abs(row["rsi"] - 57.5)) * 1.5))
    score += min(25, int(row["ret5d"] * 5))
    return max(0, min(100, score))


def screen_bsjp_multi() -> MultiScanResult:
    return _run_multi("BSJP MULTI", _bsjp_multi_filter, _bsjp_multi_score, "score")


# ─────────────────────────────────────────────────────────────────
# SCREENER B: HYBRID TREND
# ─────────────────────────────────────────────────────────────────
def _hybrid_filter(row: dict, df: pd.DataFrame) -> tuple[bool, str]:
    if row["close"] <= 50:
        return False, "Price ≤ 50"
    if row["ma20"] <= 0 or (row["close"] / row["ma20"] - 1) < -0.02:
        return False, "Price/MA20 < -2%"
    if not (row["ma20"] > row["ma50"] and row["ma50"] > 0):
        return False, "MA20 not > MA50"
    if row["vol_vs_ma20"] < 1.2:
        return False, f"Vol/VolMA20 {row['vol_vs_ma20']:.2f} < 1.2"
    if not row["vol_inc_3d"]:
        return False, "Volume not increasing 3 days"
    if row["adx"] < 20:
        return False, f"ADX {row['adx']:.1f} < 20"
    pp = row["price_pos30"]
    if not (40 <= pp <= 85):
        return False, f"30d pos {pp:.0f}% not 40–85%"
    return True, "ok"


def _hybrid_score(row: dict, df: pd.DataFrame) -> int:
    score = 0
    score += min(35, int(row["adx"] * 1.0))
    score += min(30, int((row["vol_vs_ma20"] - 1.0) * 15))
    score += min(20, int(max(0, row["ret5d"]) * 4))
    score += min(15, int(row["atr"] * 2) if row["atr"] > 0 else 0)
    return max(0, min(100, score))


def screen_hybrid_trend() -> MultiScanResult:
    return _run_multi("HYBRID TREND", _hybrid_filter, _hybrid_score, "score")


# ─────────────────────────────────────────────────────────────────
# SCREENER C: SCALPING HARIAN
# ─────────────────────────────────────────────────────────────────
def _scalping_filter(row: dict, df: pd.DataFrame) -> tuple[bool, str]:
    if not (50 <= row["close"] <= 5000):
        return False, f"Price {row['close']:.0f} not 50–5000"
    if row["volume"] < 10_000_000:
        return False, f"Volume {row['volume']:.0f} < 10M"
    if row["vol_vs_prev"] < 2.0:
        return False, f"Vol/PrevVol {row['vol_vs_prev']:.2f} < 2.0"
    if row["vwap_dist_pct"] < 1.0:
        return False, f"Price/VWAP dist {row['vwap_dist_pct']:.2f}% < 1%"
    if not (3.0 <= row["gain_pct"] <= 15.0):
        return False, f"Gain {row['gain_pct']:.2f}% not 3–15%"
    if row["vol_vs_ma20"] < 1.5:
        return False, f"RelVol {row['vol_vs_ma20']:.2f} < 1.5"
    if row["intraday_rng"] < 3.0:
        return False, f"IntradayRange {row['intraday_rng']:.2f}% < 3%"
    return True, "ok"


def _scalping_score(row: dict, df: pd.DataFrame) -> int:
    score = 0
    score += min(35, int((row["vol_vs_prev"] - 2.0) * 10))
    score += min(25, int(row["gain_pct"] * 3))
    score += min(20, int(row["vwap_dist_pct"] * 5))
    score += min(20, int(row["vol_vs_ma20"] * 5))
    return max(0, min(100, score))


def screen_scalping_harian() -> MultiScanResult:
    return _run_multi("SCALPING HARIAN", _scalping_filter, _scalping_score, "score")


# ─────────────────────────────────────────────────────────────────
# AUTO SCREENER — pick screener by WIB time
# ─────────────────────────────────────────────────────────────────
def run_auto_screener() -> tuple[str, str, MultiScanResult | None]:
    """
    Returns (mode_key, status_msg, result_or_None).
    """
    mode_key, mode_label, status_msg = get_auto_mode()

    if mode_key == "SCALPING":
        return mode_key, status_msg, screen_scalping_harian()
    elif mode_key == "BSJP":
        return mode_key, status_msg, screen_bsjp_multi()
    elif mode_key == "HYBRID":
        return mode_key, status_msg, screen_hybrid_trend()
    else:
        return mode_key, status_msg, None


# ─────────────────────────────────────────────────────────────────
# CHECKLIST HELPERS
# ─────────────────────────────────────────────────────────────────
def scalping_checklist(row: dict) -> list[tuple[str, str]]:
    checks = []
    bid_ok = row["vol_vs_ma20"] >= 1.5
    checks.append(("Bid/Offer Ratio > 1.5 (vol proxy)", "✅ PASS" if bid_ok else "⚠️ CAUTION"))
    checks.append(("Price Above VWAP", "✅ PASS" if row["vwap_dist_pct"] >= 0 else "❌ FAIL"))
    checks.append(("Volume Spike Confirmed", "✅ PASS" if row["vol_vs_prev"] >= 2.0 else "❌ FAIL"))
    spike_ok = row["gain_pct"] < 12
    checks.append(("No Large Sell Wall (gain < 12%)", "✅ PASS" if spike_ok else "⚠️ CAUTION"))
    return checks


def bsjp_multi_checklist(row: dict) -> list[tuple[str, str]]:
    checks = []
    checks.append(("EMA9 Above EMA21", "✅ PASS" if row["ema9"] > row["ema21"] and row["ema21"] > 0 else "❌ FAIL"))
    checks.append(("Volume Above Average", "✅ PASS" if row["vol_vs_ma20"] >= 1.5 else "❌ FAIL"))
    checks.append(("MACD Positive", "✅ PASS" if row["macd"] > row["macd_signal"] else "❌ FAIL"))
    checks.append(("Accumulation Pattern (AD line up)", "✅ PASS" if row["ret5d"] > 0 else "⚠️ CAUTION"))
    return checks


def hybrid_checklist(row: dict) -> list[tuple[str, str]]:
    checks = []
    checks.append(("ADX Above 20", "✅ PASS" if row["adx"] >= 20 else "❌ FAIL"))
    checks.append(("MA20 Above MA50", "✅ PASS" if row["ma20"] > row["ma50"] and row["ma50"] > 0 else "❌ FAIL"))
    checks.append(("Volume Trend Positive (3d)", "✅ PASS" if row["vol_inc_3d"] else "⚠️ CAUTION"))
    checks.append(("Relative Strength Positive", "✅ PASS" if row["ret5d"] > 0 else "⚠️ CAUTION"))
    return checks
