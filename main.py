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
        await update.message.reply_text(
            "🔥 ARA Hunter Scan\n\n"
            "BBRI.JK\n"
            "BMRI.JK\n"
            "TLKM.JK"
        )

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