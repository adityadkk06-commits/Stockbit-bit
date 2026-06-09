"""
top_gainer.py — Standalone TOP GAINER HUNTER screener.
Completely independent module. Does NOT modify any existing screener.
Uses Yahoo Finance OHLCV data only.

Filters applied:
  Price 50–500 IDR | Change >2% | Vol Ratio >1.5x
  Transaction Value 3B–10B IDR | Volume 300K–500K lots
  Close > MA20 | Today's High = 20-day Rolling High (breakout)

Filters NOT available from Yahoo Finance daily OHLCV:
  Frequency (trades/session) — shown as N/A
  Net Buy Foreign            — shown as N/A
"""

import logging
import numpy as np
import pandas as pd
from fetcher import fetch_all
from config import STOCK_UNIVERSE

logger = logging.getLogger(__name__)

TG_MAX_RESULTS  = 10
TG_NEAR_MISS    = 5


# ─────────────────────────────────────────────────────────────────
# SAFE HELPERS
# ─────────────────────────────────────────────────────────────────
def _f(val, fb: float = 0.0) -> float:
    try:
        v = float(val)
        return fb if (np.isnan(v) or np.isinf(v)) else v
    except Exception:
        return fb


# ─────────────────────────────────────────────────────────────────
# RESULT CLASS
# ─────────────────────────────────────────────────────────────────
class TopGainerResult:
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
def compute_tg_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df   = df.copy()
    c, v = df["Close"], df["Volume"]
    h, l = df["High"],  df["Low"]

    df["TG_MA20"]     = c.rolling(20).mean()
    df["TG_VolMA20"]  = v.rolling(20).mean()
    df["TG_High20"]   = h.rolling(20).max()   # 20-day rolling max high
    df["TG_VWAP"]     = (h + l + c) / 3       # daily approximation

    return df


# ─────────────────────────────────────────────────────────────────
# ROW BUILDER
# ─────────────────────────────────────────────────────────────────
def _build_tg_row(ticker: str, df: pd.DataFrame) -> dict | None:
    try:
        lat = df.iloc[-1]
        prv = df.iloc[-2]

        close  = _f(lat["Close"]);  prev_c = _f(prv["Close"])
        volume = _f(lat["Volume"]); prev_v = _f(prv["Volume"])
        high   = _f(lat["High"]);   low    = _f(lat["Low"])
        open_  = _f(lat["Open"])

        if close <= 0 or prev_c <= 0 or volume <= 0:
            return None

        gain_pct     = (close - prev_c) / prev_c * 100
        trans_val    = close * volume                    # IDR
        vol_lots     = volume / 100                      # 1 lot = 100 shares

        ma20         = _f(lat.get("TG_MA20",    0))
        vol_ma20     = _f(lat.get("TG_VolMA20", 0))
        high20       = _f(lat.get("TG_High20",  0))

        vol_ratio    = (volume / vol_ma20) if vol_ma20 > 0 else 0.0
        dist_ma20    = ((close - ma20) / ma20 * 100) if ma20 > 0 else 0.0
        breakout     = bool(high20 > 0 and high >= high20 * 0.998)  # within 0.2% of 20d high

        # Risk/reward parameters
        entry_lo = close
        entry_hi = round(close * 1.01)
        sl       = round(close * 0.97)
        tp1      = round(close * 1.03)
        tp2      = round(close * 1.06)
        risk     = max(entry_lo - sl, 1)
        reward1  = tp1 - entry_lo
        rr_ratio = round(reward1 / risk, 2) if risk > 0 else 0.0

        return dict(
            ticker      = ticker,
            close       = close,
            high        = high,
            low         = low,
            open        = open_,
            prev        = prev_c,
            volume      = volume,
            vol_lots    = vol_lots,
            prev_vol    = prev_v,
            trans_val   = trans_val,
            gain_pct    = gain_pct,
            ma20        = ma20,
            vol_ma20    = vol_ma20,
            high20      = high20,
            vol_ratio   = vol_ratio,
            dist_ma20   = dist_ma20,
            breakout    = breakout,
            entry_lo    = entry_lo,
            entry_hi    = entry_hi,
            sl          = sl,
            tp1         = tp1,
            tp2         = tp2,
            rr_ratio    = rr_ratio,
        )
    except Exception as e:
        logger.debug(f"[TG_ROW] {ticker}: {e}")
        return None


# ─────────────────────────────────────────────────────────────────
# FILTERS
# Each entry: (label, fn(row) -> bool)
# ─────────────────────────────────────────────────────────────────
TOP_GAINER_FILTERS = [
    ("Price 50–500",          lambda r: 50 <= r["close"] <= 500),
    ("Change > 2%",           lambda r: r["gain_pct"] > 2.0),
    ("Vol Ratio > 1.5x",      lambda r: r["vol_ratio"] >= 1.5),
    ("TransVal 3B–10B",       lambda r: 3_000_000_000 <= r["trans_val"] <= 10_000_000_000),
    ("Vol 300K–500K lots",    lambda r: 300_000 <= r["vol_lots"] <= 500_000),
    ("Close > MA20",          lambda r: r["ma20"] > 0 and r["close"] > r["ma20"]),
    ("20D High Breakout",     lambda r: r["breakout"]),
]


# ─────────────────────────────────────────────────────────────────
# SCORING (ranking priority per spec)
# 1. Transaction Value  2. Volume Ratio  3. Gain %  4. Breakout bonus
# ─────────────────────────────────────────────────────────────────
def _tg_score(row: dict) -> float:
    # Normalised 0–100 score
    tv_score  = min(40, max(0, (row["trans_val"] - 3e9) / 175_000_000))
    vr_score  = min(30, max(0, (row["vol_ratio"]  - 1.5) * 15))
    gain_scr  = min(20, max(0, (row["gain_pct"]   - 2.0) * 5))
    bo_bonus  = 10 if row["breakout"] else 0
    return tv_score + vr_score + gain_scr + bo_bonus


# ─────────────────────────────────────────────────────────────────
# MAIN SCREENER
# ─────────────────────────────────────────────────────────────────
def screen_top_gainer_hunter() -> TopGainerResult:
    tgr = TopGainerResult()
    n_filters = len(TOP_GAINER_FILTERS)

    stock_data = fetch_all(STOCK_UNIVERSE)
    tgr.total_fetched = len(stock_data)

    filter_pass_counts = {label: 0 for label, _ in TOP_GAINER_FILTERS}
    near_candidates: list[tuple[int, float, dict]] = []

    for ticker, df in stock_data.items():
        df  = compute_tg_indicators(df)
        row = _build_tg_row(ticker, df)

        if row is None:
            tgr.add_skip("invalid data")
            continue

        tgr.total_valid += 1

        passed_count = 0
        first_fail   = None

        for label, fn in TOP_GAINER_FILTERS:
            try:
                ok = fn(row)
            except Exception:
                ok = False
            if ok:
                filter_pass_counts[label] += 1
                passed_count += 1
            elif first_fail is None:
                first_fail = label

        if passed_count == n_filters:
            row["score"]      = _tg_score(row)
            row["pass_count"] = passed_count
            row["pass_pct"]   = 100
            tgr.total_passed += 1
            tgr.matched.append(row)
        else:
            if first_fail:
                tgr.add_skip(first_fail)
            row["pass_count"] = passed_count
            row["pass_pct"]   = int(passed_count / n_filters * 100)
            near_candidates.append((passed_count, _tg_score(row), row))

    tgr.filter_counts = filter_pass_counts

    # Sort matched: by score desc (score already encodes TV > VR > Gain > Breakout)
    tgr.matched.sort(key=lambda x: x.get("score", 0), reverse=True)
    tgr.matched = tgr.matched[:TG_MAX_RESULTS]

    # Near miss: top by filters passed, then score
    near_candidates.sort(key=lambda x: (-x[0], -x[1]))
    tgr.near_miss = [r for _, _, r in near_candidates[:TG_NEAR_MISS]]

    _log_tg_debug(tgr, n_filters)
    return tgr


# ─────────────────────────────────────────────────────────────────
# DEBUG LOGGER
# ─────────────────────────────────────────────────────────────────
def _log_tg_debug(tgr: TopGainerResult, n_filters: int):
    logger.info("=" * 40)
    logger.info(" TOP GAINER HUNTER — DEBUG REPORT")
    logger.info("=" * 40)
    logger.info(f"  Fetched : {tgr.total_fetched}")
    logger.info(f"  Valid   : {tgr.total_valid}")
    logger.info(f"  Passed  : {tgr.total_passed}")
    logger.info(f"  Results : {len(tgr.matched)}")
    logger.info("-" * 40)
    for label, count in tgr.filter_counts.items():
        pct = int(count / max(tgr.total_valid, 1) * 100)
        bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
        logger.info(f"  {label:<22} {count:>4}/{tgr.total_valid}  {bar}")
    logger.info("=" * 40)
