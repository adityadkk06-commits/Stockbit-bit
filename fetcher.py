"""
fetcher.py — Direct Yahoo Finance v8 API data fetcher.
Replaces yfinance's broken download(), which returns empty responses from Replit.
Uses concurrent ThreadPoolExecutor for fast parallel downloads.
"""

import time
import logging
import threading
import requests
import pandas as pd
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import DATA_PERIOD, DATA_INTERVAL, MIN_ROWS, RETRY_ATTEMPTS, RETRY_DELAY_SEC

logger = logging.getLogger(__name__)

# ── Browser-like headers to avoid Yahoo Finance 401/empty responses ──
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer":         "https://finance.yahoo.com/",
    "Origin":          "https://finance.yahoo.com",
}

# Shared session — connection-pooling for speed
_SESSION = requests.Session()
_SESSION.headers.update(_HEADERS)

# ── Short-lived cache: avoids re-downloading data within the same minute ──
_CACHE:     dict[str, tuple[float, pd.DataFrame]] = {}
_CACHE_TTL: float = 60.0          # seconds
_CACHE_LOCK = threading.Lock()


def _yahoo_url(symbol: str, host: str = "query1") -> str:
    return (
        f"https://{host}.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?range={DATA_PERIOD}&interval={DATA_INTERVAL}&includePrePost=false"
    )


def _parse_chart(symbol: str, data: dict) -> pd.DataFrame | None:
    """Convert Yahoo Finance v8 chart JSON into an OHLCV DataFrame."""
    try:
        result = data.get("chart", {}).get("result")
        if not result:
            err = data.get("chart", {}).get("error", {})
            logger.debug(f"[PARSE] {symbol} — no result: {err}")
            return None

        chart      = result[0]
        meta       = chart.get("meta", {})
        market_cap = float(meta.get("regularMarketCap", 0) or 0)
        timestamps = chart.get("timestamp", [])
        quote      = chart.get("indicators", {}).get("quote", [{}])[0]
        adjclose_list = (
            chart.get("indicators", {})
            .get("adjclose", [{}])[0]
            .get("adjclose", [])
        )

        if not timestamps or not quote:
            logger.debug(f"[PARSE] {symbol} — empty timestamps or quote")
            return None

        opens   = quote.get("open",   [None] * len(timestamps))
        highs   = quote.get("high",   [None] * len(timestamps))
        lows    = quote.get("low",    [None] * len(timestamps))
        closes  = quote.get("close",  [None] * len(timestamps))
        volumes = quote.get("volume", [None] * len(timestamps))

        # Use adjclose if available, else close
        adj = adjclose_list if adjclose_list else closes

        df = pd.DataFrame({
            "Open":   [float(v) if v is not None else np.nan for v in opens],
            "High":   [float(v) if v is not None else np.nan for v in highs],
            "Low":    [float(v) if v is not None else np.nan for v in lows],
            "Close":  [float(v) if v is not None else np.nan for v in adj],
            "Volume": [float(v) if v is not None else np.nan for v in volumes],
        }, index=pd.to_datetime(timestamps, unit="s", utc=True).tz_convert("Asia/Jakarta"))

        df.index = df.index.normalize()                # Strip time, keep date
        df = df[~df.index.duplicated(keep="last")]     # Remove duplicate dates
        df = df.dropna(subset=["Close", "Volume"])     # Drop rows missing core data
        df = df.sort_index()
        df["MarketCap"] = market_cap                   # IDR from Yahoo meta

        return df
    except Exception as e:
        logger.debug(f"[PARSE] {symbol} — exception: {e}")
        return None


def _fetch_one(ticker: str, attempt: int = 0) -> tuple[str, pd.DataFrame | None]:
    """Download OHLCV data for a single IDX ticker (appends .JK automatically)."""
    # ── Cache hit ──
    with _CACHE_LOCK:
        entry = _CACHE.get(ticker)
        if entry is not None:
            ts, df = entry
            if time.monotonic() - ts < _CACHE_TTL:
                return ticker, df.copy()
            del _CACHE[ticker]

    symbol = f"{ticker}.JK"

    # Try query1 first, fall back to query2 on failure
    for host in ("query1", "query2"):
        url = _yahoo_url(symbol, host)
        try:
            resp = _SESSION.get(url, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                df   = _parse_chart(symbol, data)
                if df is not None and len(df) >= MIN_ROWS:
                    with _CACHE_LOCK:
                        _CACHE[ticker] = (time.monotonic(), df)
                    return ticker, df
                # got a response but insufficient data — no point retrying other host
                rows = len(df) if df is not None else 0
                logger.debug(f"[SKIP] {ticker} — {rows} rows (need {MIN_ROWS})")
                return ticker, None
            logger.debug(f"[FETCH] {ticker} HTTP {resp.status_code} via {host}")
        except Exception as e:
            logger.debug(f"[FETCH] {ticker} via {host} error: {e}")

    # Both hosts failed — retry with delay
    if attempt < RETRY_ATTEMPTS - 1:
        time.sleep(RETRY_DELAY_SEC)
        return _fetch_one(ticker, attempt + 1)

    logger.debug(f"[FAIL] {ticker} after {RETRY_ATTEMPTS} attempts")
    return ticker, None


def fetch_all(universe: list[str], max_workers: int = 15) -> dict[str, pd.DataFrame]:
    """
    Concurrently fetch OHLCV data for all tickers in the universe.
    Returns {ticker: DataFrame} for successfully downloaded stocks.
    Cache avoids re-downloading within 60 seconds.
    """
    total   = len(universe)
    results = {}
    failed  = 0

    logger.info(f"[FETCH] Downloading {total} tickers with {max_workers} workers …")

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_fetch_one, t): t for t in universe}
        for future in as_completed(futures):
            ticker, df = future.result()
            if df is not None:
                results[ticker] = df
            else:
                failed += 1

    logger.info(
        f"[FETCH] Done — {len(results)}/{total} loaded "
        f"({failed} failed/insufficient data)"
    )

    # ── Sample log: show last candle of first successful ticker ──
    for sample_ticker, sample_df in list(results.items())[:1]:
        row = sample_df.iloc[-1]
        logger.info(
            f"[SAMPLE] {sample_ticker}: "
            f"Close={row['Close']:.0f}  "
            f"Volume={row['Volume']:.0f}  "
            f"High={row['High']:.0f}  "
            f"Low={row['Low']:.0f}"
        )

    return results
