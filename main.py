from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import os

TOKEN = os.getenv("BOT_TOKEN")

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

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = update.message.text

        if text == "🔥 ARA Hunter":

        await update.message.reply_text("🔍 Scanning ARA Hunter...")

        hasil = []

        stocks = [
            "BBCA.JK","BBRI.JK","BMRI.JK","TLKM.JK","ASII.JK",
            "ADRO.JK","ANTM.JK","MDKA.JK","GOTO.JK","CPIN.JK",
            "ICBP.JK","INDF.JK","BRPT.JK","AMMN.JK","PGEO.JK",
            "HUMI.JK","MBMA.JK","PTBA.JK","MEDC.JK","UNTR.JK"
        ]

        import yfinance as yf

        for kode in stocks:

            try:

                df = yf.download(kode, period="1mo", interval="1d")

                if len(df) < 5:
                    continue

                close = float(df["Close"].iloc[-1])
                prev = float(df["Close"].iloc[-2])

                ma5 = float(df["Close"].tail(5).mean())

                volume_today = float(df["Volume"].iloc[-1])
                volume_prev = float(df["Volume"].iloc[-2])

                value = close * volume_today

                vol_ratio = volume_today / volume_prev if volume_prev > 0 else 0

                if (
                    close > ma5 and
                    close > prev * 1.05 and
                    vol_ratio > 1 and
                    value > 5000000000
                ):

                    hasil.append(
                        f"🔥 {kode}\n"
                        f"Price: {round(close,2)}\n"
                        f"MA5: {round(ma5,2)}\n"
                        f"Prev: {round(prev,2)}\n"
                        f"Vol x: {round(vol_ratio,2)}\n"
                        f"Value: Rp {int(value):,}\n"
                    )

            except:
                pass

        if hasil:
            final_text = "\n".join(hasil[:10])
        else:
            final_text = "❌ Tidak ada saham sesuai filter."

        await update.message.reply_text(final_text)

    elif text == "🏆 Top Gainers":
        await update.message.reply_text(
            "🏆 Top Gainers Hari Ini"
        )

    elif text == "📈 Top Signals":
        await update.message.reply_text(
            "📈 Top Signals"
        )

    elif text == "📊 Market":
        await update.message.reply_text(
            "📊 Market Overview"
        )

    elif text == "🌡️ Heatmap":
        await update.message.reply_text(
            "🌡️ Heatmap IHSG"
        )

    elif text == "❓ Help":
        await update.message.reply_text(
            "Gunakan tombol menu untuk scan saham."
        )

app = Application.builder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT, button_handler))

print("Bot running...")
app.run_polling()