import os
import threading
from flask import Flask
from telegram import Update, Bot
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes, CommandHandler

# === Config ===
BOT_TOKEN = os.getenv("BOT_TOKEN")  # Reads from environment
CHANNEL_IDS = ["-1003052492544"]

# === Dummy Flask Web Server (for Render free plan) ===
app_web = Flask(__name__)

@app_web.route('/')
def home():
    return "✅ Telegram bot is running on Render!"

def run_web():
    port = int(os.getenv("PORT", 10000))  # Use Render’s PORT if available
    app_web.run(host="0.0.0.0", port=port)


# === Telegram Bot Logic ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Hi! Send me any message or photo — I’ll post it to all channels.")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot = Bot(token=BOT_TOKEN)
    if update.message.text:
        for cid in CHANNEL_IDS:
            await bot.send_message(chat_id=cid, text=update.message.text)
    elif update.message.photo:
        photo = update.message.photo[-1].file_id
        for cid in CHANNEL_IDS:
            await bot.send_photo(chat_id=cid, photo=photo, caption=update.message.caption or "")
    elif update.message.video:
        video = update.message.video.file_id
        for cid in CHANNEL_IDS:
            await bot.send_video(chat_id=cid, video=video, caption=update.message.caption or "")
    await update.message.reply_text("✅ Sent to all channels!")

app_tg = ApplicationBuilder().token(BOT_TOKEN).build()
app_tg.add_handler(CommandHandler("start", start))
app_tg.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, broadcast))

def run_bot():
    print("🚀 Bot is running...")
    app_tg.run_polling()

# === Run both web + bot ===
if __name__ == "__main__":
    threading.Thread(target=run_web).start()
    threading.Thread(target=run_bot).start()

