from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)

import os
import yfinance as yf
import pandas as pd
import ta

from screener import run_screener
from chart import generate_chart
TOKEN = os.getenv("BOT_TOKEN")

stocks = [
    "BBCA.JK","BBRI.JK","BMRI.JK","TLKM.JK","ASII.JK",
    "ADRO.JK","ANTM.JK","MDKA.JK","GOTO.JK","CPIN.JK",
    "ICBP.JK","INDF.JK","BRPT.JK","AMMN.JK","PGEO.JK",
    "HUMI.JK","MBMA.JK","PTBA.JK","MEDC.JK","UNTR.JK"
]

# =========================
# ANALYZE STOCK
# =========================
def analyze_stock(symbol):

    try:

        df = yf.download(
            symbol,
            period="3mo",
            interval="1d",
            progress=False
        )

        if df.empty or len(df) < 30:
            return None

        close = df["Close"].squeeze()

        ema9 = ta.trend.ema_indicator(close, window=9)
        ema21 = ta.trend.ema_indicator(close, window=21)

        rsi = ta.momentum.rsi(close, window=14)

        last_price = float(close.iloc[-1])
        prev_price = float(close.iloc[-2])

        last_ema9 = float(ema9.iloc[-1])
        last_ema21 = float(ema21.iloc[-1])

        last_rsi = float(rsi.iloc[-1])

        volume_today = float(df["Volume"].iloc[-1])
        volume_prev = float(df["Volume"].iloc[-2])

        vol_ratio = (
            volume_today / volume_prev
            if volume_prev > 0 else 0
        )

        value = last_price * volume_today

        score = 0

        # =========================
        # RULES
        # =========================

        if last_price > last_ema9:
            score += 15

        if last_ema9 > last_ema21:
            score += 20

        if last_price > prev_price * 1.05:
            score += 25

        if vol_ratio > 1.2:
            score += 15

        if value > 5000000000:
            score += 15

        if 55 < last_rsi < 75:
            score += 10

        # =========================
        # SIGNAL
        # =========================

        if score >= 70:
            status = "🚀 STRONG"
        elif score >= 50:
            status = "🟢 GOOD"
        else:
            status = "⚪ WEAK"

        return {
            "symbol": symbol,
            "price": last_price,
            "ema9": last_ema9,
            "ema21": last_ema21,
            "rsi": last_rsi,
            "volume": vol_ratio,
            "value": value,
            "score": score,
            "status": status
        }

    except:
        return None

# =========================
# START
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    keyboard = [
        ["🔥 ARA Hunter", "🏆 Top Gainers"],
        ["📈 Top Signals", "📊 Market"],
        ["🌡️ Heatmap", "❓ Help"]
    ]

    reply_markup = ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True
    )

    await update.message.reply_text(
        "📈 IHSG Scanner Bot Aktif",
        reply_markup=reply_markup
    )

# =========================
# BUTTON HANDLER
# =========================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = update.message.text

    # =========================
    # ARA HUNTER
    # =========================
    if text == "🔥 ARA Hunter":

        await update.message.reply_text(
            "🔍 Scanning ARA Hunter..."
        )

        results = []

        for stock in stocks:

            result = analyze_stock(stock)

            if result and result["score"] >= 70:

                results.append(result)

        results = sorted(
            results,
            key=lambda x: x["score"],
            reverse=True
        )

        if results:

            msg = ""

            for r in results[:10]:

                msg += (
                    f"{r['status']} {r['symbol']}\n"
                    f"Price: {round(r['price'],2)}\n"
                    f"EMA9: {round(r['ema9'],2)}\n"
                    f"EMA21: {round(r['ema21'],2)}\n"
                    f"RSI: {round(r['rsi'],1)}\n"
                    f"Vol x: {round(r['volume'],2)}\n"
                    f"Value: Rp {int(r['value']):,}\n"
                    f"Score: {r['score']}/100\n\n"
                )

        else:
            msg = "❌ Tidak ada saham sesuai filter."

        await update.message.reply_text(msg)

    # =========================
    # TOP GAINERS
    # =========================
    elif text == "🏆 Top Gainers":

       results = run_screener()

       if len(results) == 0:

        await update.message.reply_text(
            "No stocks passed screener."
        )

       else:

        msg = "🏆 TOP GAINERS\n\n"

        for r in results:

            msg += (
                f"📈 {r['Ticker']}\n"
                f"Price: Rp {r['Price']}\n"
                f"Change: +{r['Change%']}%\n"
                f"Vol Ratio: {r['VolRatio']}x\n\n"
            )

        chart = generate_chart(r['Ticker'] + ".JK")

        with open(chart, "rb") as photo:

        await update.message.reply_photo(
        photo=photo,
        caption=msg
    )
    # =========================
    # TOP SIGNALS
    # =========================
    elif text == "📈 Top Signals":

        signals = []

        for stock in stocks:

            result = analyze_stock(stock)

            if result:
                signals.append(result)

        signals = sorted(
            signals,
            key=lambda x: x["score"],
            reverse=True
        )

        msg = "📈 TOP SIGNALS\n\n"

        for s in signals[:10]:

            msg += (
                f"{s['symbol']} "
                f"({s['score']}/100)\n"
            )

        await update.message.reply_text(msg)

    # =========================
    # MARKET
    # =========================
    elif text == "📊 Market":

        bullish = 0
        bearish = 0

        for stock in stocks:

            result = analyze_stock(stock)

            if result:

                if result["ema9"] > result["ema21"]:
                    bullish += 1
                else:
                    bearish += 1

        total = bullish + bearish

        if bullish > bearish:
            regime = "🟢 BULLISH"
        else:
            regime = "🔴 BEARISH"

        msg = (
            f"📊 MARKET REGIME\n\n"
            f"Bullish: {bullish}\n"
            f"Bearish: {bearish}\n"
            f"Total: {total}\n\n"
            f"Status: {regime}"
        )

        await update.message.reply_text(msg)

    # =========================
    # HEATMAP
    # =========================
    elif text == "🌡️ Heatmap":

        msg = (
            "🌡️ HEATMAP IHSG\n\n"
            "🏦 Banking : 🟢 Strong\n"
            "⛏ Mining : 🟢 Strong\n"
            "📡 Telco : ⚪ Neutral\n"
            "🏭 Consumer : 🔴 Weak\n"
            "🏗 Property : 🔴 Weak"
        )

        await update.message.reply_text(msg)

    # =========================
    # HELP
    # =========================
    elif text == "❓ Help":

        await update.message.reply_text(
            "Gunakan tombol menu untuk scanning saham IHSG."
        )

# =========================
# RUN BOT
# =========================
app = Application.builder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))

app.add_handler(
    MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        button_handler
    )
)

print("Bot IHSG running...")

app.run_polling()