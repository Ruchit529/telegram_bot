import os
import asyncio
from flask import Flask, request
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from googletrans import Translator

# === CONFIG ===
BOT_TOKEN = os.getenv("BOT_TOKEN", "8554458574:AAHmpmEOGfjfNTSUDSLp0gBLyDLLEs_IxCM")
CHANNEL_IDS = ["-1003052492544","1003238213356"]
APP_URL = os.getenv("APP_URL", "https://telegrambot-pi-green.vercel.app")

translator = Translator()
app = Flask(__name__)
bot = Bot(token=BOT_TOKEN)

# === Telegram bot application ===
application = Application.builder().token(BOT_TOKEN).build()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Send any message, photo, or video — I’ll translate captions to English and send to channels.")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.caption or update.message.text or ""
    if text:
        translated = translator.translate(text, dest="en").text
    else:
        translated = ""

    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        for cid in CHANNEL_IDS:
            await bot.send_photo(chat_id=cid, photo=file_id, caption=translated)
    elif update.message.video:
        file_id = update.message.video.file_id
        for cid in CHANNEL_IDS:
            await bot.send_video(chat_id=cid, video=file_id, caption=translated)
    elif text:
        for cid in CHANNEL_IDS:
            await bot.send_message(chat_id=cid, text=translated)
    else:
        await update.message.reply_text("⚠️ Unsupported message type.")
        return

    await update.message.reply_text("✅ Sent to all channels!")

application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, broadcast))

# === Flask route for Telegram webhook ===
@app.route(f"/webhook/{BOT_TOKEN}", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    update = Update.de_json(data, bot)
    asyncio.run(application.process_update(update))
    return "ok", 200

# === Root route ===
@app.route("/")
def home():
    return "✅ Telegram bot is live on Vercel!", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
