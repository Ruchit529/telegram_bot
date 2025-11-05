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
from telegram.error import TelegramError
from telegram.helpers import escape_markdown

# === CONFIGURATION ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_IDS = ["-1003052492544", "-1003238213356"]
ALLOWED_USERS = [7173549132]
SELF_URL = os.getenv("SELF_URL", "https://telegram_bot_w8pe.onrender.com")

translator = GoogleTranslator(source="auto", target="en")
pending_messages = {}
MESSAGE_TIMEOUT = 120  # seconds

# === FLASK SERVER ===
app_web = Flask(__name__)

@app_web.route('/')
def home():
    return "✅ Telegram bot is running!", 200

def run_web():
    port = int(os.getenv("PORT", 10000))
    app_web.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

def ping_self():
    while True:
        try:
            requests.get(SELF_URL)
        except:
            pass
        time.sleep(300)

# === CLEANUP ===
def cleanup_pending():
    now = time.time()
    expired = [u for u, d in pending_messages.items() if now - d["time"] > MESSAGE_TIMEOUT]
    for u in expired:
        del pending_messages[u]

# === BOT HANDLERS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ALLOWED_USERS:
        return await update.message.reply_text("🚫 Unauthorized user.")
    await update.message.reply_text("👋 Send a message, photo, or video. Edit it anytime before confirming!")

async def process_message(msg, context):
    """Core message logic for both new and edited messages"""
    cleanup_pending()
    user_id = msg.from_user.id
    if user_id not in ALLOWED_USERS:
        return

    text = msg.caption or msg.text or ""
    text = translator.translate(text) if text else ""
    safe_text = escape_markdown(text, version=2)

    photo = msg.photo[-1].file_id if msg.photo else None
    video = msg.video.file_id if msg.video else None

    pending_messages[user_id] = {
        "type": "photo" if photo else "video" if video else "text",
        "file_id": photo or video,
        "text": text,
        "time": time.time()
    }

    preview = f"*Preview:* {safe_text}\n\n_Send to channel? (Yes / No)_"

    if photo:
        await msg.reply_photo(photo=photo, caption=preview, parse_mode="MarkdownV2")
    elif video:
        await msg.reply_video(video=video, caption=preview, parse_mode="MarkdownV2")
    else:
        await msg.reply_text(preview, parse_mode="MarkdownV2")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in ALLOWED_USERS:
        return await update.message.reply_text("🚫 Unauthorized user.")

    if user_id in pending_messages:
        response = (update.message.text or "").strip().lower()
        data = pending_messages[user_id]

        if response in ["yes", "y", "send", "ok"]:
            for cid in CHANNEL_IDS:
                try:
                    escaped = escape_markdown(data["text"], version=2)
                    if data["type"] == "text":
                        await context.bot.send_message(cid, escaped, parse_mode="MarkdownV2")
                    elif data["type"] == "photo":
                        await context.bot.send_photo(cid, data["file_id"], caption=escaped, parse_mode="MarkdownV2")
                    elif data["type"] == "video":
                        await context.bot.send_video(cid, data["file_id"], caption=escaped, parse_mode="MarkdownV2")
                except TelegramError as e:
                    print(f"⚠️ Send error: {e}")
            await update.message.reply_text("✅ Message sent to all channels!")
            del pending_messages[user_id]
            return

        elif response in ["no", "n", "cancel"]:
            await update.message.reply_text("❌ Cancelled.")
            del pending_messages[user_id]
            return

        else:
            pending_messages[user_id]["text"] = update.message.text
            await update.message.reply_text("✏️ Text updated. Reply 'Yes' to send.")
            return

    await process_message(update.message, context)

async def handle_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.edited_message:
        await process_message(update.edited_message, context)

# === RUN BOT ===
async def run_bot():
    app_tg = ApplicationBuilder().token(BOT_TOKEN).build()
    app_tg.add_handler(CommandHandler("start", start))
    app_tg.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO, handle_message))
    app_tg.add_handler(MessageHandler(filters.UpdateType.EDITED_MESSAGE, handle_edit))

    print("🚀 Bot running...")
    await app_tg.initialize()
    await app_tg.start()
    await app_tg.updater.start_polling()
    await asyncio.Event().wait()

# === MAIN ===
if __name__ == "__main__":
    threading.Thread(target=run_web).start()
    threading.Thread(target=ping_self, daemon=True).start()
    asyncio.run(run_bot())
