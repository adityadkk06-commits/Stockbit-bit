import yfinance as yf
import pandas as pd
import numpy as np
import logging
from config import (
    STOCK_UNIVERSE, DATA_PERIOD, DATA_INTERVAL,
    BIG_ACCUM_FILTERS, BSJP_FILTERS, ARA_FILTERS,
    MAX_RESULTS, TP_PERCENT, SL_PERCENT
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# DATA FETCHER
# Downloads OHLCV data for a single ticker from yfinance
# Returns a DataFrame or None if download fails
# ─────────────────────────────────────────────────────────────────
def fetch_stock_data(ticker: str) -> pd.DataFrame | None:
    symbol = f"{ticker}.JK"
    try:
        df = yf.download(
            symbol,
            period=DATA_PERIOD,
            interval=DATA_INTERVAL,
            progress=False,
            auto_adjust=True,
        )
        if df is None or df.empty or len(df) < 25:
            return None

        # Flatten multi-level columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df.index = pd.to_datetime(df.index)
        df = df.sort_index()
        return df
    except Exception as e:
        logger.warning(f"Failed to fetch {ticker}: {e}")
        return None


# ─────────────────────────────────────────────────────────────────
# INDICATORS
# Computes moving averages and other signals on a DataFrame
# ─────────────────────────────────────────────────────────────────
def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["MA5"]  = df["Close"].rolling(5).mean()
    df["MA20"] = df["Close"].rolling(20).mean()
    df["MA50"] = df["Close"].rolling(50).mean()
    df["VolMA5"]  = df["Volume"].rolling(5).mean()
    df["VolMA20"] = df["Volume"].rolling(20).mean()

    # Accumulation/Distribution Line (simplified Williams AD)
    high_low = df["High"] - df["Low"]
    high_low = high_low.replace(0, np.nan)
    clv = (
        (df["Close"] - df["Low"]) - (df["High"] - df["Close"])
    ) / high_low
    df["AD"] = (clv * df["Volume"]).cumsum()

    # Rate of change of AD as a score proxy (0-100 clamped)
    ad_change = df["AD"].pct_change(5).fillna(0) * 100
    df["AccumScore"] = ad_change.clip(0, 100)

    return df


# ─────────────────────────────────────────────────────────────────
# PROBABILITY SCORE
# Composite score (0-100) based on four factors:
#   1. Volume surge vs MA20
#   2. Price momentum (% gain today)
#   3. MA trend (price above MA20 and MA50)
#   4. Price breakout (price vs MA5)
# ─────────────────────────────────────────────────────────────────
def compute_probability(row: dict) -> int:
    score = 0

    # 1. Volume surge (max 30 pts)
    vol_ratio = row.get("vol_ratio", 1.0)
    score += min(30, int((vol_ratio - 1.0) * 15))

    # 2. Price momentum (max 30 pts)
    gain_pct = row.get("gain_pct", 0.0)
    score += min(30, int(gain_pct * 5))

    # 3. MA trend (max 25 pts)
    if row.get("above_ma20"):
        score += 15
    if row.get("above_ma50"):
        score += 10

    # 4. Price above MA5 breakout (max 15 pts)
    if row.get("above_ma5"):
        score += 15

    return max(0, min(100, score))


# ─────────────────────────────────────────────────────────────────
# BUILD RESULT DICT
# Packages a single stock into a standardised result dictionary
# ─────────────────────────────────────────────────────────────────
def build_result(ticker: str, df: pd.DataFrame) -> dict | None:
    try:
        latest = df.iloc[-1]
        prev   = df.iloc[-2]

        close  = float(latest["Close"])
        prev_c = float(prev["Close"])
        volume = float(latest["Volume"])
        value  = close * volume         # Estimated trade value in IDR

        gain_pct  = ((close - prev_c) / prev_c) * 100 if prev_c else 0
        vol_ratio = (
            float(latest["VolMA5"]) / float(latest["VolMA20"])
            if float(latest["VolMA20"]) > 0 else 1.0
        )

        row = {
            "ticker":    ticker,
            "close":     close,
            "prev":      prev_c,
            "volume":    volume,
            "value":     value,
            "gain_pct":  gain_pct,
            "vol_ratio": vol_ratio,
            "above_ma5":  close >= float(latest["MA5"])  if not np.isnan(latest["MA5"])  else False,
            "above_ma20": close >= float(latest["MA20"]) if not np.isnan(latest["MA20"]) else False,
            "above_ma50": close >= float(latest["MA50"]) if not np.isnan(latest["MA50"]) else False,
            "ma20":      float(latest["MA20"]) if not np.isnan(latest["MA20"]) else 0,
            "ma50":      float(latest["MA50"]) if not np.isnan(latest["MA50"]) else 0,
            "ma5":       float(latest["MA5"])  if not np.isnan(latest["MA5"])  else 0,
            "vol_ma20":  float(latest["VolMA20"]) if not np.isnan(latest["VolMA20"]) else 0,
            "open":      float(latest["Open"]),
            "accum":     float(latest["AccumScore"]) if not np.isnan(latest["AccumScore"]) else 0,
        }

        row["probability"] = compute_probability(row)
        row["tp"] = round(close * (1 + TP_PERCENT))
        row["sl"] = round(close * (1 - SL_PERCENT))

        return row
    except Exception as e:
        logger.warning(f"build_result failed for {ticker}: {e}")
        return None


# ─────────────────────────────────────────────────────────────────
# SCREENER 1: BIG ACCUMULATION
# Cheap stocks with strong accumulation and volume surge
# ─────────────────────────────────────────────────────────────────
def screen_big_accumulation(universe: list[str]) -> list[dict]:
    f = BIG_ACCUM_FILTERS
    results = []

    for ticker in universe:
        df = fetch_stock_data(ticker)
        if df is None:
            continue
        df = compute_indicators(df)

        row = build_result(ticker, df)
        if row is None:
            continue

        # Apply filters
        if (
            row["accum"]     >= f["accum_dist_min"]
            and row["value"] >= f["min_value"]
            and row["ma20"]  >  row["ma50"]          # MA20 > MA50
            and row["close"] <= f["max_price"]
            and row["vol_ratio"] >= f["vol_surge_ratio"]
            and row["gain_pct"]  > 0                 # Price > Previous Price
        ):
            results.append(row)

    return sorted(results, key=lambda x: x["probability"], reverse=True)[:MAX_RESULTS]


# ─────────────────────────────────────────────────────────────────
# SCREENER 2: BSJP
# Strong bullish continuation with foreign accumulation
# ─────────────────────────────────────────────────────────────────
def screen_bsjp(universe: list[str]) -> list[dict]:
    f = BSJP_FILTERS
    results = []

    for ticker in universe:
        df = fetch_stock_data(ticker)
        if df is None:
            continue
        df = compute_indicators(df)

        row = build_result(ticker, df)
        if row is None:
            continue

        # Net foreign buy streak proxy: positive AD for last N days
        try:
            ad_series = df["AD"].iloc[-f["net_foreign_streak"]:]
            ad_rising = all(
                ad_series.iloc[i] > ad_series.iloc[i - 1]
                for i in range(1, len(ad_series))
            )
        except Exception:
            ad_rising = False

        latest = df.iloc[-1]
        prev   = df.iloc[-2]
        vol_vs_prev = (
            float(latest["Volume"]) / float(prev["Volume"])
            if float(prev["Volume"]) > 0 else 0
        )

        # Apply filters
        if (
            row["value"]       >= f["min_value"]
            and vol_vs_prev    >= f["vol_vs_prev_ratio"]
            and row["above_ma20"]
            and row["ma20"]    > row["ma50"]
            and row["close"]   >= row["prev"] * f["price_gain_ratio"]
            and row["above_ma5"]
            and row["vol_ratio"] >= f["vol_vs_ma20_ratio"]
            and ad_rising
        ):
            results.append(row)

    return sorted(results, key=lambda x: x["probability"], reverse=True)[:MAX_RESULTS]


# ─────────────────────────────────────────────────────────────────
# SCREENER 3: ARA HUNTER
# Stocks with Auto Reject Atas (upper limit) momentum potential
# ─────────────────────────────────────────────────────────────────
def screen_ara_hunter(universe: list[str]) -> list[dict]:
    f = ARA_FILTERS
    results = []

    for ticker in universe:
        df = fetch_stock_data(ticker)
        if df is None:
            continue
        df = compute_indicators(df)

        row = build_result(ticker, df)
        if row is None:
            continue

        latest = df.iloc[-1]
        prev   = df.iloc[-2]
        vol_vs_prev = (
            float(latest["Volume"]) / float(prev["Volume"])
            if float(prev["Volume"]) > 0 else 0
        )

        # Apply filters
        if (
            row["above_ma5"]
            and row["close"]   >= row["prev"] * f["price_gain_ratio"]
            and row["close"]   >  row["open"]
            and vol_vs_prev    >= f["vol_vs_prev_ratio"]
            and row["value"]   >= f["min_value"]
        ):
            results.append(row)

    return sorted(results, key=lambda x: x["probability"], reverse=True)[:MAX_RESULTS]
