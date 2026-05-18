"""
screener.py — Screening logic for IDX stocks.
Filters match exactly the rules defined by the user (screenshots).
"""

import logging
import numpy as np
import pandas as pd
from fetcher import fetch_all
from config import (
    STOCK_UNIVERSE,
    BIG_ACCUM_FILTERS, BSJP_FILTERS, ARA_FILTERS,
    MAX_RESULTS, TP_PERCENT, SL_PERCENT,
)

logger = logging.getLogger(__name__)


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
# INDICATORS  (SMA only — as required by the screener rules)
# ─────────────────────────────────────────────────────────────────
def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c, v = df["Close"], df["Volume"]

    # Price moving averages
    df["MA5"]  = c.rolling(5).mean()
    df["MA20"] = c.rolling(20).mean()
    df["MA50"] = c.rolling(50).mean()

    # Volume moving averages
    df["VolMA5"]  = v.rolling(5).mean()
    df["VolMA20"] = v.rolling(20).mean()

    # Accumulation / Distribution Line (Bandar Accum/Dist proxy)
    hl  = (df["High"] - df["Low"]).replace(0, np.nan)
    clv = ((c - df["Low"]) - (df["High"] - c)) / hl
    df["AD"] = (clv.fillna(0) * v).cumsum()

    # AccumScore: 5-day pct change of AD, clamped 0–100
    # Represents Bandar Accum/Dist strength
    df["AccumScore"] = df["AD"].pct_change(5).fillna(0).mul(100).clip(0, 100)

    return df


# ─────────────────────────────────────────────────────────────────
# BUILD ROW DICT — all signal values for the latest candle
# ─────────────────────────────────────────────────────────────────
def build_row(ticker: str, df: pd.DataFrame) -> tuple[dict | None, str]:
    try:
        lat, prv = df.iloc[-1], df.iloc[-2]

        close  = _f(lat["Close"]);  prev_c = _f(prv["Close"])
        volume = _f(lat["Volume"]); prev_v = _f(prv["Volume"])
        open_  = _f(lat["Open"])

        if close <= 0 or prev_c <= 0:
            return None, "invalid price"
        if volume <= 0:
            return None, "zero volume"

        ma5    = _f(lat["MA5"])
        ma20   = _f(lat["MA20"])
        ma50   = _f(lat["MA50"])
        vma5   = _f(lat["VolMA5"])
        vma20  = _f(lat["VolMA20"])
        accum  = _f(lat["AccumScore"])

        gain_pct          = ((close - prev_c) / prev_c) * 100
        vol_ma5_vs_ma20   = _ratio(vma5, vma20, fb=0.0)   # VolMA5 / VolMA20
        vol_today_vs_ma20 = _ratio(volume, vma20, fb=0.0)  # Today vol / VolMA20
        vol_today_vs_prev = _ratio(volume, prev_v, fb=0.0) # Today vol / Prev vol

        row = dict(
            ticker=ticker,
            close=close,
            prev=prev_c,
            open=open_,
            volume=volume,
            value=close * volume,
            gain_pct=gain_pct,
            ma5=ma5,
            ma20=ma20,
            ma50=ma50,
            vma5=vma5,
            vma20=vma20,
            accum=accum,
            vol_ma5_vs_ma20=vol_ma5_vs_ma20,
            vol_today_vs_ma20=vol_today_vs_ma20,
            vol_today_vs_prev=vol_today_vs_prev,
        )

        # Probability score (for sorting results)
        score = 0
        score += min(30, int((vol_today_vs_ma20 - 1.0) * 10))
        score += min(30, int(gain_pct * 5))
        if ma20 > 0 and close >= ma20: score += 15
        if ma50 > 0 and ma20 > ma50:   score += 15
        if ma5  > 0 and close >= ma5:  score += 10
        row["probability"] = max(0, min(100, score))
        row["tp"] = round(close * (1 + TP_PERCENT))
        row["sl"] = round(close * (1 - SL_PERCENT))

        return row, "ok"
    except Exception as e:
        return None, f"exception: {e}"


# ─────────────────────────────────────────────────────────────────
# SCAN RESULT — returned by every public screener function
# ─────────────────────────────────────────────────────────────────
class ScanResult:
    def __init__(self, name: str):
        self.name = name
        self.matched:   list[dict] = []
        self.near_miss: list[dict] = []
        self.total_fetched  = 0
        self.total_passed   = 0
        self.skip_reasons: dict[str, int] = {}

    def add_skip(self, reason: str):
        self.skip_reasons[reason] = self.skip_reasons.get(reason, 0) + 1

    def log_summary(self):
        logger.info(
            f"[{self.name}] Scanned {self.total_fetched} | "
            f"Passed {self.total_passed} | "
            f"Skipped {self.total_fetched - self.total_passed}"
        )
        for reason, count in sorted(self.skip_reasons.items(), key=lambda x: -x[1])[:8]:
            logger.info(f"  ↳ '{reason}': {count}")


# ─────────────────────────────────────────────────────────────────
# GENERIC RUNNER
# ─────────────────────────────────────────────────────────────────
def _run(name: str, filter_fn, near_miss_fn=None) -> ScanResult:
    sr = ScanResult(name)
    stock_data = fetch_all(STOCK_UNIVERSE)
    sr.total_fetched = len(stock_data)

    near_candidates: list[tuple[int, dict]] = []

    for ticker, df in stock_data.items():
        df  = compute_indicators(df)
        row, reason = build_row(ticker, df)

        if row is None:
            sr.add_skip(reason)
            continue

        passed, fail_reason = filter_fn(row, df)

        if passed:
            sr.total_passed += 1
            sr.matched.append(row)
        else:
            sr.add_skip(fail_reason)
            if near_miss_fn:
                nm_score = near_miss_fn(row, df)
                if nm_score > 0:
                    near_candidates.append((nm_score, row))

    sr.matched.sort(key=lambda x: x["probability"], reverse=True)
    sr.matched = sr.matched[:MAX_RESULTS]

    near_candidates.sort(key=lambda x: (-x[0], -x[1]["probability"]))
    sr.near_miss = [r for _, r in near_candidates[:5]]

    sr.log_summary()
    return sr


# ─────────────────────────────────────────────────────────────────
# AD STREAK HELPER (Net Foreign Buy Streak proxy)
# ─────────────────────────────────────────────────────────────────
def _ad_streak(df: pd.DataFrame, days: int) -> bool:
    """Returns True if the AD line has risen for `days` consecutive days."""
    try:
        ad = df["AD"].iloc[-(days + 1):]
        return all(ad.iloc[i] > ad.iloc[i - 1] for i in range(1, len(ad)))
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────
# SCREENER 1: BIG ACCUMULATION
#
# Rules (exact):
#   1. Bandar Accum/Dist > 25
#   2. Value > 3,000,000,000
#   3. Price MA20 > 1 × Price MA50
#   4. Price < 500
#   5. Volume MA5 > 1.3 × Volume MA20
#   6. Price > 1 × Previous Price
# ─────────────────────────────────────────────────────────────────
def _big_accum_filter(row: dict, df: pd.DataFrame) -> tuple[bool, str]:
    f = BIG_ACCUM_FILTERS

    if row["accum"] <= f["accum_dist_min"]:
        return False, f"Bandar A/D {row['accum']:.1f} ≤ {f['accum_dist_min']}"
    if row["value"] <= f["min_value"]:
        return False, "Value ≤ 3,000,000,000"
    if not (row["ma20"] > row["ma50"] and row["ma20"] > 0 and row["ma50"] > 0):
        return False, "MA20 not > MA50"
    if row["close"] >= f["max_price"]:
        return False, f"Price {row['close']:.0f} ≥ 500"
    if row["vol_ma5_vs_ma20"] <= f["vol_surge_ratio"]:
        return False, f"VolMA5/VolMA20 {row['vol_ma5_vs_ma20']:.2f} ≤ 1.3"
    if row["close"] <= row["prev"]:
        return False, f"Price {row['close']:.0f} not > Prev {row['prev']:.0f}"

    return True, "ok"


def _big_accum_near(row: dict, df: pd.DataFrame) -> int:
    f = BIG_ACCUM_FILTERS
    score = 0
    if row["accum"] > f["accum_dist_min"]:                          score += 1
    if row["value"] > f["min_value"]:                               score += 1
    if row["ma20"] > row["ma50"] and row["ma50"] > 0:               score += 1
    if row["close"] < f["max_price"]:                               score += 1
    if row["vol_ma5_vs_ma20"] > f["vol_surge_ratio"]:               score += 1
    if row["close"] > row["prev"]:                                  score += 1
    return score if score >= 3 else 0


def screen_big_accumulation() -> ScanResult:
    return _run("BIG ACCUMULATION", _big_accum_filter, _big_accum_near)


# ─────────────────────────────────────────────────────────────────
# SCREENER 2: BSJP
#
# Rules (exact):
#   1. Value > 10,000,000,000
#   2. Volume > 1.2 × Previous Volume
#   3. Price > 1 × Price MA20
#   4. Price MA20 > 1 × Price MA50
#   5. Price > 1.01 × Previous Price
#   6. Price >= 1 × Price MA5
#   7. Volume > 2 × Volume MA20
#   8. Net Foreign Buy Streak >= 2
# ─────────────────────────────────────────────────────────────────
def _bsjp_filter(row: dict, df: pd.DataFrame) -> tuple[bool, str]:
    f = BSJP_FILTERS

    if row["value"] <= f["min_value"]:
        return False, "Value ≤ 10,000,000,000"
    if row["vol_today_vs_prev"] <= f["vol_vs_prev_ratio"]:
        return False, f"Volume/PrevVol {row['vol_today_vs_prev']:.2f} ≤ 1.2"
    if not (row["ma20"] > 0 and row["close"] > row["ma20"]):
        return False, "Price not > MA20"
    if not (row["ma20"] > row["ma50"] and row["ma50"] > 0):
        return False, "MA20 not > MA50"
    if row["close"] <= row["prev"] * f["price_gain_ratio"]:
        return False, f"Price not > 1.01 × Prev (gain {row['gain_pct']:.2f}%)"
    if not (row["ma5"] > 0 and row["close"] >= row["ma5"]):
        return False, "Price not >= MA5"
    if row["vol_today_vs_ma20"] <= f["vol_vs_ma20_ratio"]:
        return False, f"Volume/VolMA20 {row['vol_today_vs_ma20']:.2f} ≤ 2.0"
    if not _ad_streak(df, f["net_foreign_streak"]):
        return False, "Net Foreign Buy Streak < 2"

    return True, "ok"


def _bsjp_near(row: dict, df: pd.DataFrame) -> int:
    f = BSJP_FILTERS
    score = 0
    if row["value"] > f["min_value"]:                               score += 1
    if row["vol_today_vs_prev"] > f["vol_vs_prev_ratio"]:           score += 1
    if row["ma20"] > 0 and row["close"] > row["ma20"]:              score += 1
    if row["ma20"] > row["ma50"] and row["ma50"] > 0:               score += 1
    if row["close"] > row["prev"] * f["price_gain_ratio"]:          score += 1
    if row["ma5"] > 0 and row["close"] >= row["ma5"]:               score += 1
    if row["vol_today_vs_ma20"] > f["vol_vs_ma20_ratio"]:           score += 1
    if _ad_streak(df, f["net_foreign_streak"]):                     score += 1
    return score if score >= 4 else 0


def screen_bsjp() -> ScanResult:
    return _run("BSJP", _bsjp_filter, _bsjp_near)


# ─────────────────────────────────────────────────────────────────
# SCREENER 3: ARA HUNTER
#
# Rules (exact):
#   1. Price > 1 × Price MA5
#   2. Price > 1.05 × Previous Price
#   3. Price > 1 × Open Price
#   4. Volume > 0.2 × Previous Volume
#   5. Value > 5,000,000,000
# ─────────────────────────────────────────────────────────────────
def _ara_filter(row: dict, df: pd.DataFrame) -> tuple[bool, str]:
    f = ARA_FILTERS

    if not (row["ma5"] > 0 and row["close"] > row["ma5"]):
        return False, "Price not > MA5"
    if row["close"] <= row["prev"] * f["price_gain_ratio"]:
        return False, f"Price not > 1.05 × Prev (gain {row['gain_pct']:.2f}%)"
    if row["close"] <= row["open"]:
        return False, f"Price {row['close']:.0f} not > Open {row['open']:.0f}"
    if row["vol_today_vs_prev"] <= f["vol_vs_prev_ratio"]:
        return False, f"Volume/PrevVol {row['vol_today_vs_prev']:.2f} ≤ 0.2"
    if row["value"] <= f["min_value"]:
        return False, "Value ≤ 5,000,000,000"

    return True, "ok"


def _ara_near(row: dict, df: pd.DataFrame) -> int:
    f = ARA_FILTERS
    score = 0
    if row["ma5"] > 0 and row["close"] > row["ma5"]:               score += 1
    if row["close"] > row["prev"] * f["price_gain_ratio"]:          score += 1
    if row["close"] > row["open"]:                                  score += 1
    if row["vol_today_vs_prev"] > f["vol_vs_prev_ratio"]:           score += 1
    if row["value"] > f["min_value"]:                               score += 1
    return score if score >= 3 else 0


def screen_ara_hunter() -> ScanResult:
    return _run("ARA HUNTER", _ara_filter, _ara_near)
