import os
import asyncio
import threading
from flask import Flask
from telegram import Update, Bot
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from deep_translator import GoogleTranslator
from telegram.error import TelegramError

# === CONFIGURATION ===
BOT_TOKEN = os.getenv("BOT_TOKEN") or "YOUR_BOT_TOKEN_HERE"
CHANNEL_IDS = ["-1003052492544"]  # Add more channel IDs if needed
pending_messages = {}

# === SIMPLE FLASK WEB SERVER ===
app_web = Flask(__name__)

@app_web.route('/')
def home():
    return "✅ Telegram bot is running on Render!", 200

def run_web():
    port = int(os.getenv("PORT", 10000))
    print(f"🌐 Web server running on port {port}")
    app_web.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

# === TRANSLATION FUNCTION (replaces googletrans) ===
async def translate_to_english(text: str) -> str:
    if not text:
        return ""
    loop = asyncio.get_running_loop()
    # Run translation in thread pool to avoid blocking
    return await loop.run_in_executor(None, lambda: GoogleTranslator(source='auto', target='en').translate(text))

# === TELEGRAM BOT HANDLERS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Send me any text, photo, or video.\n"
        "I’ll translate it to English and ask before posting to your channels."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.caption or update.message.text
    photo = update.message.photo
    video = update.message.video
    bot = Bot(token=BOT_TOKEN)

    # === Confirmation replies ===
    if user_id in pending_messages:
        response = (update.message.text or "").strip().lower()
        data = pending_messages[user_id]

        if response in ["yes", "y", "ok", "send"]:
            for cid in CHANNEL_IDS:
                try:
                    if data["type"] == "text":
                        await bot.send_message(chat_id=cid, text=data["text"])
                    elif data["type"] == "photo":
                        await bot.send_photo(chat_id=cid, photo=data["file_id"], caption=data["text"])
                    elif data["type"] == "video":
                        await bot.send_video(chat_id=cid, video=data["file_id"], caption=data["text"])
                except TelegramError as e:
                    print(f"⚠️ Error sending to {cid}: {e}")

            await update.message.reply_text("✅ Sent to all channels!")
            del pending_messages[user_id]

        elif response in ["no", "n", "cancel"]:
            await update.message.reply_text("
