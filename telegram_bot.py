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
from googletrans import Translator
from telegram.error import TelegramError

# === CONFIGURATION ===
BOT_TOKEN = os.getenv("BOT_TOKEN") or "YOUR_BOT_TOKEN_HERE"
CHANNEL_IDS = ["-1003052492544"]  # Add your channel IDs here
translator = Translator()
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

# === HELPER FUNCTION ===
async def translate_to_english(text: str) -> str:
    if not text:
        return ""
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, lambda: translator.translate(text, dest="en"))
    return result.text

# === TELEGRAM BOT HANDLERS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Send me text, photo, or video.\n"
        "I’ll translate it to English and ask before posting to the channels."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.caption or update.message.text
    photo = update.message.photo
    video = update.message.video
    bot = Bot(token=BOT_TOKEN)

    # === Confirmation reply handling ===
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
            await update.message.reply_text("❌ Cancelled.")
            del pending_messages[user_id]
        else:
            await update.message.reply_text("Please reply with 'Yes' or 'No'.")
        return

    # === New message processing ===
    translated = await translate_to_english(text)

    if photo:
        file_id = photo[-1].file_id
        pending_messages[user_id] = {"type": "photo", "file_id": file_id, "text": translated}
        await update.message.reply_photo(
            photo=file_id,
            caption=f"🖼 Translated Caption:\n{translated}\n\nSend to channels? (Yes / No)"
        )

    elif video:
        file_id = video.file_id
        pending_messages[user_id] = {"type": "video", "file_id": file_id, "text": translated}
        await update.message.reply_video(
            video=file_id,
            caption=f"🎥 Translated Caption:\n{translated}\n\nSend to channels? (Yes / No)"
        )

    elif text:
        pending_messages[user_id] = {"type": "text", "text": translated}
        await update.message.reply_text(f"{translated}\n\nSend to channels? (Yes / No)")

    else:
        await update.message.reply_text("⚠️ Please send text, photo, or video.")

# === BOT RUNNER ===
async def run_bot():
    app_tg = ApplicationBuilder().token(BOT_TOKEN).build()
    app_tg.add_handler(CommandHandler("start", start))
    app_tg.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

    print("🚀 Telegram bot is running...")
    await app_tg.initialize()
    await app_tg.start()
    await app_tg.updater.start_polling()
    await asyncio.Event().wait()  # Keeps bot running forever

if __name__ == "__main__":
    threading.Thread(target=run_web).start()
    asyncio.run(run_bot())
