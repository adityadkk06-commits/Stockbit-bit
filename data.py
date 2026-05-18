import yfinance as yf
import pandas as pd
import logging

logger = logging.getLogger(__name__)

SYMBOL = "GC=F"


def _clean_df(df):
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df = df[['Open', 'High', 'Low', 'Close', 'Volume']].copy()
    df.dropna(inplace=True)
    df.index = pd.to_datetime(df.index)
    return df


def get_h1_data(periods=200):
    try:
        df = yf.download(SYMBOL, interval="1h", period="30d", progress=False, auto_adjust=True)
        df = _clean_df(df)
        if df is None:
            return None
        return df.tail(periods)
    except Exception as e:
        logger.error(f"H1 data fetch error: {e}")
        return None


def get_m5_data(periods=100):
    try:
        df = yf.download(SYMBOL, interval="5m", period="5d", progress=False, auto_adjust=True)
        df = _clean_df(df)
        if df is None:
            return None
        return df.tail(periods)
    except Exception as e:
        logger.error(f"M5 data fetch error: {e}")
        return None
