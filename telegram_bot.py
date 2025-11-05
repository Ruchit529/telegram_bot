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
GROUP_LINK = "https://t.me/steam_games_chatt"

translator = GoogleTranslator(source="auto", target="en")
pending_messages = {}
MESSAGE_TIMEOUT = 120  # 2 minutes timeout

# === FLASK SERVER ===
app_web = Flask(__name__)

@app_web.route('/')
def home():
    return "✅ Telegram bot is running!", 200

def run_web():
    port = int(os.getenv("PORT", 10000))
    print(f"🌐 Flask web server running on port {port}")
    app_web.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

# === KEEP ALIVE ===
def ping_self():
    while True:
        try:
            res = requests.get(SELF_URL)
            print(f"🔁 Pinged {SELF_URL} ({res.status_code})")
        except Exception as e:
            print(f"⚠️ Ping failed: {e}")
        time.sleep(300)

# === CLEANUP ===
def cleanup_pending():
    now = time.time()
    for uid in list(pending_messages.keys()):
        if now - pending_messages[uid]["time"] > MESSAGE_TIMEOUT:
            del pending_messages[uid]

# === TEXT TEMPLATE ===
TEMPLATE_PREFIX = "👇👇👇\n\n"
TEMPLATE_SUFFIX = "\n\n👉 [JOIN GROUP]({})".format(GROUP_LINK)

def build_template(text: str):
    return f"{TEMPLATE_PREFIX}{text}{TEMPLATE_SUFFIX}"

# === TELEGRAM LOGIC ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ALLOWED_USERS:
        return await update.message.reply_text("🚫 Unauthorized user.")
    await update.message.reply_text("👋 Send text, photo, or video — then reply 'Yes' to confirm sending.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cleanup_pending()
    msg = update.message
    uid = msg.from_user.id
    if uid not in ALLOWED_USERS:
        return await msg.reply_text("🚫 Unauthorized user.")

    text = msg.caption or msg.text
    photo = msg.photo
    video = msg.video

    # === Confirm or Edit ===
    if uid in pending_messages:
        response = (msg.text or "").strip().lower()
        if response in ["yes", "y", "ok", "send"]:
            data = pending_messages[uid]
            formatted = build_template(data["text"])
            for cid in CHANNEL_IDS:
                try:
                    if data["type"] == "text":
                        await context.bot.send_message(chat_id=cid, text=formatted, parse_mode="Markdown")
                    elif data["type"] == "photo":
                        await context.bot.send_photo(chat_id=cid, photo=data["file_id"], caption=formatted, parse_mode="Markdown")
                    elif data["type"] == "video":
                        await context.bot.send_video(chat_id=cid, video=data["file_id"], caption=formatted, parse_mode="Markdown")
                except TelegramError as e:
                    print(f"⚠️ Send failed: {e}")
            await msg.reply_text("✅ Sent to all channels!")
            del pending_messages[uid]
            return

        elif response in ["no", "n", "cancel"]:
            await msg.reply_text("❌ Cancelled.")
            del pending_messages[uid]
            return

        else:
            pending_messages[uid]["text"] = msg.text
            await msg.reply_text(f"✏️ Updated text:\n\n{msg.text}\n\nNow reply 'Yes' to send.")
            return

    # === New message ===
    translated = translator.translate(text) if text else ""
    if photo:
        file_id = photo[-1].file_id
        pending_messages[uid] = {"type": "photo", "file_id": file_id, "text": translated, "time": time.time()}
        await msg.reply_photo(photo=file_id, caption=f"{translated}\n\nSend to channel? (Yes / No)")
    elif video:
        file_id = video.file_id
        pending_messages[uid] = {"type": "video", "file_id": file_id, "text": translated, "time": time.time()}
        await msg.reply_video(video=file_id, caption=f"{translated}\n\nSend to channel? (Yes / No)")
    elif text:
        pending_messages[uid] = {"type": "text", "text": translated, "time": time.time()}
        await msg.reply_text(f"{translated}\n\nSend to channel? (Yes / No)")
    else:
        await msg.reply_text("⚠️ Please send text, image, or video.")

# === RUN BOT ASYNC ===
async def run_bot():
    app_tg = ApplicationBuilder().token(BOT_TOKEN).build()
    app_tg.add_handler(CommandHandler("start", start))
    app_tg.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO, handle_message))
    print("🚀 Telegram bot connected to Telegram API")
    await app_tg.run_polling(close_loop=False)

# === MAIN ===
if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    threading.Thread(target=ping_self, daemon=True).start()

    loop = asyncio.get_event_loop()
    loop.create_task(run_bot())
    print("✅ Bot and Flask initialized... waiting for updates.")
    loop.run_forever()
