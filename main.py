from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    Filters,
    ContextTypes
)

import os

# IMPORT DARI SCREENER.PY
from screener import run_screener
from bandarmology import run_bandarmology

TOKEN = os.getenv("BOT_TOKEN")


# ==========================================
# START
# ==========================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    keyboard = [
    ["📈 Screener"],
    ["🏦 Bandarmology"]
]

    reply_markup = ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True
    )

    await update.message.reply_text(
        "Bot Screener Aktif",
        reply_markup=reply_markup
    )


# ==========================================
# SCREENER BUTTON
# ==========================================

async def screener(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "Scanning semua saham IDX..."
    )

    results = run_screener()

    if not results:

        await update.message.reply_text(
            "Tidak ada saham yang lolos filter"
        )

        return

    message = "TOP SCREENER\n\n"

    for stock in results[:10]:

        message += (
            f"{stock['symbol']}\n"
            f"Price : {stock['price']}\n"
            f"Value : {stock['value']:,}\n\n"
        )

    await update.message.reply_text(message)


# ==========================================
# BANDARMOLOGY BUTTON
# ==========================================

async def bandarmology(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "Scanning bandar accumulation..."
    )

    results = run_bandarmology()

    if not results:

        await update.message.reply_text(
            "Tidak ada saham bandar accumulation"
        )

        return

    message = "🏦 BANDARMOLOGY\n\n"

    for stock in results[:10]:

        message += (
            f"{stock['symbol']}\n"
            f"Price : {stock['price']}\n"
            f"Accumulation : {stock['accumulation']}\n"
            f"Value : {stock['value']:,}\n"
            f"TP : {stock['tp']}\n"
            f"SL : {stock['sl']}\n\n"
        )

    await update.message.reply_text(message)

# ==========================================
# HANDLE BUTTON
# ==========================================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = update.message.text

    # ======================================
    # SCREENER
    # ======================================

    if text == "📈 Screener":

        await screener(update, context)

    # ======================================
    # BANDARMOLOGY
    # ======================================

    elif text == "🏦 Bandarmology":

        await bandarmology(update, context)

# ==========================================
# MAIN
# ==========================================

def main():

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("screener", screener))

    print("Bot Running...")

    app.run_polling()


if __name__ == "__main__":
    main()