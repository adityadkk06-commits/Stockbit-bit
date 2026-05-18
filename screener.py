# ==========================================
# ANALYZE STOCK
# ==========================================

def analyze_stock(symbol):

    try:

        stock = yf.Ticker(symbol)

        df = stock.history(period="3mo")

        if len(df) < 20:
            return None

        # ==================================
        # BASIC DATA
        # ==================================

        close = df["Close"]
        open_price = df["Open"]
        volume = df["Volume"]

        last_price = close.iloc[-1]
        prev_price = close.iloc[-2]

        last_open = open_price.iloc[-1]

        last_volume = volume.iloc[-1]
        prev_volume = volume.iloc[-2]

        # ==================================
        # MOVING AVERAGE
        # ==================================

        ma5 = close.tail(5).mean()

        # ==================================
        # VALUE
        # ==================================

        value = last_price * last_volume

        # ==================================
        # FILTERS
        # ==================================

        # Price > 1 x Price MA 5
        if last_price <= ma5:
            return None

        # Price > 1.05 x Previous Price
        if last_price <= (prev_price * 1.05):
            return None

        # Price > 1 x Open Price
        if last_price <= last_open:
            return None

        # Volume > 0.2 x Previous Volume
        if last_volume <= (prev_volume * 0.2):
            return None

        # Value > 5,000,000,000
        if value <= 5_000_000_000:
            return None

        # ==================================
        # RESULT
        # ==================================

        result = {
            "symbol": symbol,
            "price": round(last_price, 2),
            "previous_price": round(prev_price, 2),
            "ma5": round(ma5, 2),
            "volume": int(last_volume),
            "previous_volume": int(prev_volume),
            "value": int(value)
        }

        return result

    except Exception as e:

        print(f"Error {symbol} : {e}")

        return None
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
# RUN SCREENER
# ==========================================

def run_screener():

    stocks = load_all_idx_stocks()

    results = []

    total = len(stocks)

    for i, symbol in enumerate(stocks):

        print(f"[{i+1}/{total}] Scanning {symbol}")

        result = analyze_stock(symbol)

        if result:
            results.append(result)

    return results