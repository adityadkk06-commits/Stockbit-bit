"""
accumulation_screener.py — Early accumulation phase detector for IDX stocks.

Finds stocks where volume has already picked up but price hasn't run yet —
smart money quietly accumulating before a breakout. The opposite of ARA Hunter
(which catches stocks that have ALREADY flown).

Adapted from the original design for Yahoo Finance OHLCV data:
  - close, high, low, volume: from Yahoo Finance ✅
  - value: derived as close × volume ✅
  - foreign_net: proxied via daily A/D Line change (actual RTI data unavailable) ⚠️
  - freq (transaction frequency): not available from Yahoo Finance — skipped ⚠️

Max achievable score with OHLCV data = 85/100.
Candidate threshold: score ≥ 60 AND volume spike AND quiet price (non-negotiable).
"""

import logging
import numpy as np
import pandas as pd
from fetcher import fetch_all
from utils import _f, _ratio
from config import STOCK_UNIVERSE, MAX_RESULTS, TP_PERCENT, SL_PERCENT

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────
ACCUM_CONFIG = {
    "price_change_min":        -2.0,           # min 1D price change % (still quiet)
    "price_change_max":         4.0,           # max 1D price change % (still quiet)
    "volume_ratio_min":         2.0,           # today vol vs 20D average
    "value_min_rupiah":   3_000_000_000,       # min transaction value (3B IDR)
    "bb_period":               20,
    "bb_width_percentile_max": 30,             # BB width below this percentile = narrow
    "ad_streak_days":           3,             # consecutive days of rising A/D line
    "ma_period":               20,
    "ma_fresh_cross_lookback":  5,             # cross must occur within last N days
    "candidate_score_min":     60,             # minimum score to be a candidate
}

ACCUM_MAX_RESULTS = MAX_RESULTS
ACCUM_NEAR_MISS   = 5


# ─────────────────────────────────────────────────────────────────
# RESULT CLASS
# ─────────────────────────────────────────────────────────────────
class AccumResult:
    __slots__ = ("matched", "near_miss", "total_fetched", "total_valid",
                 "total_passed", "filter_counts", "skip_reasons")

    def __init__(self):
        self.matched:       list[dict] = []
        self.near_miss:     list[dict] = []
        self.total_fetched: int = 0
        self.total_valid:   int = 0
        self.total_passed:  int = 0
        self.filter_counts: dict[str, int] = {}
        self.skip_reasons:  dict[str, int] = {}

    def add_skip(self, reason: str):
        self.skip_reasons[reason] = self.skip_reasons.get(reason, 0) + 1


# ─────────────────────────────────────────────────────────────────
# INDICATORS
# ─────────────────────────────────────────────────────────────────
def compute_accum_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c, v, h, l = df["Close"], df["Volume"], df["High"], df["Low"]

    period = ACCUM_CONFIG["bb_period"]

    df["MA20"]    = c.rolling(period).mean()
    df["VolMA20"] = v.rolling(period).mean()

    # Bollinger Bands
    std           = c.rolling(period).std()
    df["BB_Upper"] = df["MA20"] + 2 * std
    df["BB_Lower"] = df["MA20"] - 2 * std
    # BB width as % of MA (so it's comparable across price levels)
    df["BB_Width"] = (df["BB_Upper"] - df["BB_Lower"]) / df["MA20"].replace(0, np.nan) * 100

    # Accumulation / Distribution Line (proxy for foreign net flow)
    hl  = (h - l).replace(0, np.nan)
    clv = ((c - l) - (h - c)) / hl
    df["AD"] = (clv.fillna(0) * v).cumsum()

    return df


# ─────────────────────────────────────────────────────────────────
# SIGNAL HELPERS
# ─────────────────────────────────────────────────────────────────
def _volume_ratio(df: pd.DataFrame) -> float:
    """Today's volume vs 20-day average of the prior period."""
    v    = df["Volume"]
    vma  = _f(df["VolMA20"].iloc[-1])
    return _ratio(v.iloc[-1], vma)


def _bb_width_percentile(df: pd.DataFrame) -> float | None:
    """Where does today's BB width sit in its own historical distribution?
    Lower percentile = narrower = price is coiling = potential breakout."""
    widths = df["BB_Width"].dropna()
    if len(widths) < 20:
        return None
    current = widths.iloc[-1]
    return float((widths < current).mean() * 100)


def _ma_fresh_cross(df: pd.DataFrame) -> bool:
    """True if price just crossed above MA20 within the last N days."""
    cfg      = ACCUM_CONFIG
    period   = cfg["ma_period"]
    lookback = cfg["ma_fresh_cross_lookback"]
    c        = df["Close"]
    ma       = df["MA20"]

    if len(c) < period + lookback + 1:
        return False

    above  = (c > ma)
    recent = above.iloc[-(lookback + 1):]
    # fresh cross = False→True transition, and it's True now
    return bool(recent.iloc[-1] and (not recent.iloc[0]) and recent.any())


def _ad_streak(df: pd.DataFrame, days: int) -> bool:
    """True if the A/D line has risen for `days` consecutive days (proxy for
    sustained foreign accumulation / institutional buying)."""
    try:
        ad = df["AD"].iloc[-(days + 1):]
        return all(ad.iloc[i] > ad.iloc[i - 1] for i in range(1, len(ad)))
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────
# SCORE ENGINE
# ─────────────────────────────────────────────────────────────────
def _score_ticker(ticker: str, df: pd.DataFrame) -> dict | None:
    """Evaluate one ticker and return a scored dict, or None if data insufficient."""
    try:
        cfg = ACCUM_CONFIG
        lat = df.iloc[-1]
        prv = df.iloc[-2]

        close  = _f(lat["Close"])
        prev_c = _f(prv["Close"])
        volume = _f(lat["Volume"])

        if close <= 0 or prev_c <= 0 or volume <= 0:
            return None

        gain_pct = (close - prev_c) / prev_c * 100
        value    = close * volume
        vol_ratio = _volume_ratio(df)
        bb_pct   = _bb_width_percentile(df)
        fresh_cross = _ma_fresh_cross(df)
        ad_ok    = _ad_streak(df, cfg["ad_streak_days"])
        ma20     = _f(lat["MA20"])

        tags  = []
        score = 0

        # 1. Quiet price (weight 20)
        quiet = cfg["price_change_min"] <= gain_pct <= cfg["price_change_max"]
        if quiet:
            score += 20
            tags.append("quiet_price")

        # 2. Volume spike ≥ 2× MA20 (weight 25 — most important)
        vol_ok = vol_ratio >= cfg["volume_ratio_min"]
        if vol_ok:
            score += 25
            tags.append(f"vol_{vol_ratio:.1f}x")

        # 3. Transaction value ≥ 3B IDR (weight 10)
        val_ok = value >= cfg["value_min_rupiah"]
        if val_ok:
            score += 10
            tags.append("liquid")

        # 4. Fresh MA20 cross (weight 15)
        if fresh_cross:
            score += 15
            tags.append("fresh_cross_MA20")

        # 5. BB width narrow vs history (weight 15)
        bb_narrow = bb_pct is not None and bb_pct <= cfg["bb_width_percentile_max"]
        if bb_narrow:
            score += 15
            tags.append("tight_bb")

        # 6. A/D streak (weight 10 — proxy for foreign net buy; actual RTI data N/A)
        if ad_ok:
            score += 10
            tags.append("AD_streak")

        # Non-negotiable conditions for is_candidate
        is_candidate = (
            score >= cfg["candidate_score_min"]
            and vol_ok
            and quiet
        )

        return dict(
            ticker       = ticker,
            close        = close,
            prev         = prev_c,
            volume       = volume,
            value        = value,
            gain_pct     = gain_pct,
            vol_ratio    = vol_ratio,
            ma20         = ma20,
            bb_pct       = round(bb_pct, 1) if bb_pct is not None else None,
            fresh_cross  = fresh_cross,
            ad_streak    = ad_ok,
            score        = score,
            is_candidate = is_candidate,
            tags         = tags,
            tp           = round(close * (1 + TP_PERCENT)),
            sl           = round(close * (1 - SL_PERCENT)),
        )
    except Exception as e:
        logger.debug(f"[ACCUM] {ticker}: {e}")
        return None


# ─────────────────────────────────────────────────────────────────
# MAIN SCREENER
# ─────────────────────────────────────────────────────────────────
def screen_accumulation() -> AccumResult:
    ar = AccumResult()
    near_candidates: list[dict] = []

    stock_data = fetch_all(STOCK_UNIVERSE)
    ar.total_fetched = len(stock_data)

    for ticker, df in stock_data.items():
        df  = compute_accum_indicators(df)
        row = _score_ticker(ticker, df)

        if row is None:
            ar.add_skip("invalid data")
            continue

        ar.total_valid += 1

        if row["is_candidate"]:
            ar.total_passed += 1
            ar.matched.append(row)
        else:
            # Track near-misses (passed vol + quiet but score < 60)
            if row["vol_ratio"] >= ACCUM_CONFIG["volume_ratio_min"] and \
               ACCUM_CONFIG["price_change_min"] <= row["gain_pct"] <= ACCUM_CONFIG["price_change_max"]:
                near_candidates.append(row)
            else:
                reason = "Vol < 2×MA20" if row["vol_ratio"] < ACCUM_CONFIG["volume_ratio_min"] \
                    else "Price not quiet"
                ar.add_skip(reason)

    ar.matched.sort(key=lambda x: x["score"], reverse=True)
    ar.matched = ar.matched[:ACCUM_MAX_RESULTS]

    near_candidates.sort(key=lambda x: x["score"], reverse=True)
    ar.near_miss = near_candidates[:ACCUM_NEAR_MISS]

    _log_accum_debug(ar)
    return ar


# ─────────────────────────────────────────────────────────────────
# DEBUG LOGGER
# ─────────────────────────────────────────────────────────────────
def _log_accum_debug(ar: AccumResult):
    logger.info("=" * 40)
    logger.info(" ACCUMULATION SCREENER — DEBUG REPORT")
    logger.info("=" * 40)
    logger.info(f"  Fetched   : {ar.total_fetched}")
    logger.info(f"  Valid     : {ar.total_valid}")
    logger.info(f"  Candidates: {ar.total_passed}")
    logger.info(f"  Results   : {len(ar.matched)}")
    if ar.skip_reasons:
        logger.info("  Skip reasons:")
        for r, c in sorted(ar.skip_reasons.items(), key=lambda x: -x[1])[:5]:
            logger.info(f"    {r}: {c}")
    logger.info("=" * 40)
