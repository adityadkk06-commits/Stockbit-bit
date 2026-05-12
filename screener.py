# =========================================
# screener.py
# Stock Screener IDX Style
# =========================================

import yfinance as yf
import pandas as pd
import numpy as np

# =========================================
# LIST SAHAM
# =========================================

stocks = [
    "BBCA.JK", "BMRI.JK", "BBRI.JK", "TLKM.JK",
    "ASII.JK", "ADRO.JK", "BRPT.JK", "GOTO.JK",
    "MEDC.JK", "MDKA.JK", "AMMN.JK", "PGEO.JK",
    "ANTM.JK", "INCO.JK", "CPIN.JK", "ICBP.JK",
    "ACES.JK", "AKRA.JK", "HUMI.JK", "MBMA.JK"
]

# =========================================
# RULES
# =========================================

MIN_PRICE = 100
MAX_PRICE = 2000

MIN_MARKET_CAP = 3_000_000_000_000   # 3T

MIN_VALUE_MA20 = 8_000_000_000       # 8B

MIN_VOLUME_RATIO = 1.3

MIN_PRICE_CHANGE = 2  # %

# =========================================
# FUNCTION
# =========================================

def analyze_stock(symbol):

    try:
        df = yf.download(symbol, period="3mo", interval="1d", progress=False)

        if len(df) < 25:
            return None

        close = df["Close"]
        volume = df["Volume"]

        last_price = float(close.iloc[-1])

        # ---------------------------------
        # PRICE FILTER
        # ---------------------------------

        if last_price < MIN_PRICE:
            return None

        if last_price > MAX_PRICE:
            return None

        # ---------------------------------
        # MARKET CAP
        # ---------------------------------

        stock = yf.Ticker(symbol)

        info = stock.info

        market_cap = info.get("marketCap", 0)

        if market_cap < MIN_MARKET_CAP:
            return None

        # ---------------------------------
        # VALUE MA20
        # ---------------------------------

        value = close * volume

        value_ma20 = value.rolling(20).mean().iloc[-1]

        if value_ma20 < MIN_VALUE_MA20:
            return None

        # ---------------------------------
        # VOLUME MA5 > 1.3 x MA20
        # ---------------------------------

        vol_ma5 = volume.rolling(5).mean().iloc[-1]

        vol_ma20 = volume.rolling(20).mean().iloc[-1]

        volume_ratio = vol_ma5 / vol_ma20

        if volume_ratio < MIN_VOLUME_RATIO:
            return None

        # ---------------------------------
        # PRICE CHANGE > 2%
        # ---------------------------------

        prev_close = float(close.iloc[-2])

        price_change = ((last_price - prev_close) / prev_close) * 100

        if price_change < MIN_PRICE_CHANGE:
            return None

        # ---------------------------------
        # FOREIGN FLOW
        # Tidak tersedia di Yahoo
        # Dummy PASS sementara
        # ---------------------------------

        foreign_flow = "PASS"

        # =================================
        # RESULT
        # =================================

        return {
            "Ticker": symbol.replace(".JK", ""),
            "Price": round(last_price, 2),
            "Change%": round(price_change, 2),
            "MarketCap(T)": round(market_cap / 1_000_000_000_000, 2),
            "ValueMA20(B)": round(value_ma20 / 1_000_000_000, 2),
            "VolRatio": round(volume_ratio, 2),
            "Foreign": foreign_flow
        }

    except Exception as e:
        print(f"Error {symbol}: {e}")
        return None


# =========================================
# RUN SCREENER FUNCTION
# =========================================

def run_screener():

    results = []

    print("\nScanning market...\n")

    for stock in stocks:

        result = analyze_stock(stock)

        if result:
            results.append(result)

    if len(results) == 0:
        return []

    screener_df = pd.DataFrame(results)

    screener_df = screener_df.sort_values(
        by=["VolRatio", "Change%"],
        ascending=False
    )

    return screener_df.to_dict("records")