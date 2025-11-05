import os
import asyncio
import threading
import time
import requests
from flask import Flask
from telegram import Update, MessageEntity
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
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_IDS = ["-1003052492544", "-1003238213356"]
ALLOWED_USERS = [7173549132]
SELF_URL = os.getenv("SELF_URL", "https://telegram_bot_w8pe.onrender.com")

translator = GoogleTranslator(source="auto", target="en")

pending_messages = {}
MESSAGE_TIMEOUT = 120  # 2 minutes

# === SIMPLE FLASK WEB SERVER ===
app_web = Flask(__name__)

@app_web.route('/')
def home():
    return "✅ Telegram bot is running on Render!", 200

def run_web():
    port = int(os.getenv("PORT", 10000))
    print(f"🌐 Web server running on port {port}")
    app_web.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

# === KEEP ALIVE ===
def ping_self():
    while True:
        try:
            res = requests.get(SELF_URL)
            print(f"🔁 Pinged {SELF_URL} | Status: {res.status_code}")
        except Exception as e:
            print(f"⚠️ Ping failed: {e}")
        time.sleep(300)

# === CLEANUP ===
def cleanup_pending():
    now = time.time()
    for uid in list(pending_messages.keys()):
        if now - pending_messages[uid]["time"] > MESSAGE_TIMEOUT:
            del pending_messages[uid]

# === TELEGRAM BOT LOGIC ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in ALLOWED_USERS:
        return await update.message.reply_text("🚫 You are not authorized.")
    await update.message.reply_text("👋 Send me a text, photo, or video — I’ll translate and confirm before posting.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cleanup_pending()
    user_id = update.message.from_user.id

    if user_id not in ALLOWED_USERS:
        return await update.message.reply_text("🚫 You are not authorized.")

    text = update.message.caption or update.message.text
    photo = update.message.photo
    video = update.message.video
    entities = update.message.entities or update.message.caption_entities

    # === HANDLE CONFIRMATION ===
    if user_id in pending_messages:
        response = (update.message.text or "").strip().lower()

        if response in ["yes", "y", "ok", "send"]:
            data = pending_messages[user_id]
            for cid in CHANNEL_IDS:
                try:
                    if data["type"] == "text":
                        await context.bot.send_message(
                            chat_id=cid,
                            text=data["text"],
                            entities=data["entities"]
                        )
                    elif data["type"] == "photo":
                        await context.bot.send_photo(
                            chat_id=cid,
                            photo=data["file_id"],
                            caption=data["text"],
                            caption_entities=data["entities"]
                        )
                    elif data["type"] == "video":
                        await context.bot.send_video(
                            chat_id=cid,
                            video=data["file_id"],
                            caption=data["text"],
                            caption_entities=data["entities"]
                        )
                except TelegramError as e:
                    print(f"⚠️ Telegram send error: {e}")

            await update.message.reply_text("✅ Sent to all channels!")
            del pending_messages[user_id]
            return

        elif response in ["no", "n", "cancel"]:
            await update.message.reply_text("❌ Cancelled.")
            del pending_messages[user_id]
            return

        else:
            pending_messages[user_id]["text"] = update.message.text
            pending_messages[user_id]["entities"] = update.message.entities
            await update.message.reply_text("✏️ Text updated! Reply 'Yes' to send.")
            return

    # === NEW MESSAGE ===
    translated_text = translator.translate(text) if text else text

    if photo:
        file_id = photo[-1].file_id
        pending_messages[user_id] = {
            "type": "photo",
            "file_id": file_id,
            "text": translated_text,
            "entities": entities,
            "time": time.time()
        }
        await update.message.reply_photo(
            photo=file_id,
            caption=f"{translated_text}\n\nSend to channel? (Yes / No)",
            caption_entities=entities
        )

    elif video:
        file_id = video.file_id
        pending_messages[user_id] = {
            "type": "video",
            "file_id": file_id,
            "text": translated_text,
            "entities": entities,
            "time": time.time()
        }
        await update.message.reply_video(
            video=file_id,
            caption=f"{translated_text}\n\nSend to channel? (Yes / No)",
            caption_entities=entities
        )

    elif text:
        pending_messages[user_id] = {
            "type": "text",
            "text": translated_text,
            "entities": entities,
            "time": time.time()
        }
        await update.message.reply_text(
            f"{translated_text}\n\nSend to channel? (Yes / No)",
            entities=entities
        )
    else:
        await update.message.reply_text("⚠️ Please send text, image, or video.")

# === BOT RUNNER ===
async def run_bot():
    app_tg = ApplicationBuilder().token(BOT_TOKEN).build()
    app_tg.add_handler(CommandHandler("start", start))
    app_tg.add_handler(MessageHandler(filters.ALL, handle_message))

    print("🚀 Bot is running...")
    await app_tg.initialize()
    await app_tg.start()
    await app_tg.updater.start_polling()
    await asyncio.Event().wait()

# === MAIN ===
if __name__ == "__main__":
    threading.Thread(target=run_web).start()
    threading.Thread(target=ping_self, daemon=True).start()
    asyncio.run(run_bot())
