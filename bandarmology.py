import yfinance as yf
import pandas as pd


# ==========================================
# LOAD ALL IDX STOCKS
# ==========================================

def load_all_idx_stocks():

    url = "https://www.idx.co.id/id/data-pasar/data-saham/daftar-saham"

    tables = pd.read_html(url)

    df = tables[0]

    symbols = df["Kode"].dropna().tolist()

    stocks = [f"{symbol}.JK" for symbol in symbols]

    return stocks


# ==========================================
# BANDARMOLOGY SCREENER
# ==========================================

def run_bandarmology():

    stocks = load_all_idx_stocks()

    results = []

    total = len(stocks)

    for i, symbol in enumerate(stocks):

        try:

            print(f"[{i+1}/{total}] {symbol}")

            stock = yf.Ticker(symbol)

            df = stock.history(period="1mo")

            if len(df) < 10:
                continue

            close = df["Close"]
            volume = df["Volume"]

            last_price = close.iloc[-1]

            avg_volume = volume.mean()

            last_volume = volume.iloc[-1]

            value = last_price * last_volume

            # ==================================
            # BANDAR ACCUMULATION SCORE
            # ==================================

            accumulation_score = (
                last_volume / avg_volume
            ) * 10

            # ==================================
            # FILTER
            # ==================================

            # Bandar Accum/Dist > 20
            if accumulation_score <= 20:
                continue

            # Value > 3B
            if value <= 3_000_000_000:
                continue

            results.append({
                "symbol": symbol,
                "price": round(last_price, 2),
                "value": int(value),
                "accumulation": round(accumulation_score, 2)
            })

        except Exception as e:

            print(f"ERROR {symbol} : {e}")

    results = sorted(
        results,
        key=lambda x: x["accumulation"],
        reverse=True
    )

    return results