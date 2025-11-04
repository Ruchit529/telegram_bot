import os
import asyncio
import threading
import time
import requests
from flask import Flask
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from deep_translator import GoogleTranslator
from telegram.constants import ParseMode
from telegram.error import TelegramError

# === CONFIGURATION ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_IDS = ["-1003052492544", "-1003238213356"]
ALLOWED_USERS = [7173549132]
SELF_URL = os.getenv("SELF_URL", "https://telegram_bot_w8pe.onrender.com")

translator = GoogleTranslator(source="auto", target="en")
pending_messages = {}
MESSAGE_TIMEOUT = 120  # Auto-clear old confirmations after 2 minutes

# === SIMPLE FLASK WEB SERVER ===
app_web = Flask(__name__)

@app_web.route('/')
def home():
    return "✅ Telegram bot is running on Render!", 200

def run_web():
    port = int(os.getenv("PORT", 10000))
    print(f"🌐 Web server running on port {port}")
    app_web.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

# === KEEP ALIVE PING SYSTEM ===
def ping_self():
    while True:
        try:
            res = requests.get(SELF_URL)
            print(f"🔁 Pinged {SELF_URL} | Status: {res.status_code}")
        except Exception as e:
            print(f"⚠️ Ping failed: {e}")
        time.sleep(300)

# === CLEANUP FUNCTION ===
def cleanup_pending():
    now = time.time()
    to_delete = [uid for uid, data in pending_messages.items() if now - data["time"] > MESSAGE_TIMEOUT]
    for uid in to_delete:
        del pending_messages[uid]

# === TELEGRAM BOT LOGIC ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in ALLOWED_USERS:
        return await update.message.reply_text("🚫 You are not authorized to use this bot.")
    await update.message.reply_text("👋 Hi! Send me text, photo, or video — I’ll translate and ask before posting.")

async def process_message(message, context):
    """Handles both normal and edited messages."""
    user_id = message.from_user.id
    cleanup_pending()

    if user_id not in ALLOWED_USERS:
        await message.reply_text("🚫 You are not authorized to use this bot.")
        return

    text = message.caption or message.text
    photo = message.photo
    video = message.video

    # === EDIT OR CONFIRM HANDLING ===
    if user_id in pending_messages:
        response = (message.text or "").strip()
        data = pending_messages[user_id]

        # --- Confirm ---
        if response.lower() in ["yes", "y", "ok", "send"]:
            for cid in CHANNEL_IDS:
                try:
                    if data["type"] == "text":
                        await context.bot.send_message(chat_id=cid, text=data["text"], parse_mode=ParseMode.MARKDOWN)
                    elif data["type"] == "photo":
                        await context.bot.send_photo(chat_id=cid, photo=data["file_id"], caption=data["text"], parse_mode=ParseMode.MARKDOWN)
                    elif data["type"] == "video":
                        await context.bot.send_video(chat_id=cid, video=data["file_id"], caption=data["text"], parse_mode=ParseMode.MARKDOWN)
                except TelegramError:
                    pass
            await message.reply_text("✅ Sent to all channels!")
            del pending_messages[user_id]
            return

        # --- Cancel ---
        elif response.lower() in ["no", "n", "cancel"]:
            await message.reply_text("❌ Cancelled.")
            del pending_messages[user_id]
            return

        # --- Text updated (either by edit or typing) ---
        else:
            data["text"] = response
            pending_messages[user_id] = data
            if data["type"] == "text":
                await message.reply_text(
                    f"✏️ *Updated text:*\n{response}\n\nSend to channel? (Yes / No)",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                try:
                    if data["type"] == "photo":
                        await message.reply_photo(photo=data["file_id"], caption=f"{response}\n\nSend to channel? (Yes / No)", parse_mode=ParseMode.MARKDOWN)
                    elif data["type"] == "video":
                        await message.reply_video(video=data["file_id"], caption=f"{response}\n\nSend to channel? (Yes / No)", parse_mode=ParseMode.MARKDOWN)
                except TelegramError:
                    await message.reply_text(
                        f"✏️ *Updated text:*\n{response}\n\nSend to channel? (Yes / No)",
                        parse_mode=ParseMode.MARKDOWN
                    )
            return

    # === NEW MESSAGE HANDLING ===
    translated_text = translator.translate(text) if text else ""

    if photo:
        file_id = photo[-1].file_id
        pending_messages[user_id] = {"type": "photo", "file_id": file_id, "text": translated_text, "time": time.time()}
        await message.reply_photo(photo=file_id, caption=f"{translated_text}\n\nSend to channel? (Yes / No)", parse_mode=ParseMode.MARKDOWN)

    elif video:
        file_id = video.file_id
        pending_messages[user_id] = {"type": "video", "file_id": file_id, "text": translated_text, "time": time.time()}
        await message.reply_video(video=file_id, caption=f"{translated_text}\n\nSend to channel? (Yes / No)", parse_mode=ParseMode.MARKDOWN)

    elif text:
        pending_messages[user_id] = {"type": "text", "text": translated_text, "time": time.time()}
        await message.reply_text(f"{translated_text}\n\nSend to channel? (Yes / No)", parse_mode=ParseMode.MARKDOWN)
    else:
        await message.reply_text("⚠️ Please send text, image, or video.")

# Normal messages
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await process_message(update.message, context)

# Edited messages
async def handle_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.edited_message:
        await process_message(update.edited_message, context)

# === BOT RUNNER ===
async def run_bot():
    app_tg = ApplicationBuilder().token(BOT_TOKEN).build()
    app_tg.add_handler(CommandHandler("start", start))
    app_tg.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO, handle_message))
    app_tg.add_handler(MessageHandler(filters.UpdateType.EDITED_MESSAGE, handle_edit))

    print("🚀 Telegram bot is running...")
    await app_tg.initialize()
    await app_tg.start()
    await app_tg.updater.start_polling()
    await asyncio.Event().wait()

# === MAIN ===
if __name__ == "__main__":
    threading.Thread(target=run_web).start()
    threading.Thread(target=ping_self, daemon=True).start()
    asyncio.run(run_bot())
