from telegram import ReplyKeyboardMarkup
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

keyboard = [
    ["🔥 ARA Hunter", "🏆 Top Gainers"],
    ["📈 Top Signals", "📊 Market"],
    ["🌡 Heatmap", "❓ Help"]
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
        "🔥 Scanning ARA Hunter...\n\n"
        "Rules:\n"
        "✅ Price > MA5\n"
        "✅ Gap Up > 5%\n"
        "✅ Price > Open\n"
        "✅ Volume Spike\n"
        "✅ Value > 5B"
    )

elif text == "🏆 Top Gainers":

    await update.message.reply_text(
        "🏆 Top Gainers IHSG"
    )

elif text == "📈 Top Signals":

    await scan(update, context)

elif text == "📊 Market":

    await update.message.reply_text(
        "📊 Market Overview"
    )

elif text == "🌡 Heatmap":

    await update.message.reply_text(
        "🌡 Heatmap Market"
    )

elif text == "❓ Help":

    await update.message.reply_text(
        "Gunakan menu tombol untuk scan market."
    )
  from telegram.ext import MessageHandler, filters
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("scan", scan))

app.add_handler(
    MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        button_handler
    )
)