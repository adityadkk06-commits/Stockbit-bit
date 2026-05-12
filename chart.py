import yfinance as yf
import mplfinance as mpf

def generate_chart(symbol):

    df = yf.download(
        symbol,
        period="1mo",
        interval="1d",
        progress=False
    )

    filename = f"{symbol}.png"

    mpf.plot(
        df,
        type="candle",
        style="yahoo",
        volume=True,
        mav=(9, 21),
        savefig=filename
    )

    return filename