import os
import asyncio
import threading
import time
import requests
import re
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

# === CONFIGURATION ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_IDS = ["-1003052492544", "-1003238213356"]  # ✅ your channels
ALLOWED_USERS = [7173549132]  # ✅ your Telegram user ID
SELF_URL = os.getenv("SELF_URL", "https://telegram_bot_w8pe.onrender.com")
GROUP_LINK = "https://t.me/your_group_link_here"  # ✅ your real group link

translator = GoogleTranslator(source="auto", target="en")

pending_messages = {}
MESSAGE_TIMEOUT = 120  # clear old confirmations (2 mins)


# === SIMPLE FLASK WEB SERVER ===
app_web = Flask(__name__)

@app_web.route('/')
def home():
    return "✅ Telegram bot is running on Render!", 200

def run_web():
    port = int(os.getenv("PORT", 10000))
    print(f"🌐 Web server running on port {port}")
    app_web.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


# === KEEP-ALIVE PING ===
def ping_self():
    while True:
        try:
            res = requests.get(SELF_URL)
            print(f"🔁 Pinged {SELF_URL} | Status: {res.status_code}")
        except Exception as e:
            print(f"⚠️ Ping failed: {e}")
        time.sleep(300)  # every 5 minutes


# === CLEANUP PENDING ===
def cleanup_pending():
    now = time.time()
    to_delete = [uid for uid, data in pending_messages.items() if now - data["time"] > MESSAGE_TIMEOUT]
    for uid in to_delete:
        del pending_messages[uid]


# === MARKDOWN-SAFE TEMPLATE BUILDER ===
def build_template(message_text: str) -> str:
    # Escape Markdown characters safely
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    safe_text = re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', message_text)
    return f"👇👇👇\n\n{safe_text}\n\n👉 [JOIN GROUP]({GROUP_LINK})"


# === SAFE SEND FUNCTION (split long text) ===
async def safe_send_message(bot, chat_id, text):
    for i in range(0, len(text), 4000):  # Telegram limit ~4096 chars
        await bot.send_message(
            chat_id=chat_id,
            text=text[i:i+4000],
            parse_mode="Markdown",
            disable_web_page_preview=True
        )


# === TELEGRAM BOT LOGIC ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in ALLOWED_USERS:
        return await update.message.reply_text("🚫 You are not authorized to use this bot.")
    await update.message.reply_text("👋 Hi! Send text, photo, or video — I'll translate & confirm before posting.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cleanup_pending()
    user_id = update.message.from_user.id
    if user_id not in ALLOWED_USERS:
        return await update.message.reply_text("🚫 You are not authorized to use this bot.")

    text = update.message.caption or update.message.text
    photo = update.message.photo
    video = update.message.video

    # === CONFIRMATION HANDLING ===
    if user_id in pending_messages:
        response = (update.message.text or "").strip()

        # ✅ Confirm
        if response.lower() in ["yes", "y", "ok", "send"]:
            data = pending_messages[user_id]
            formatted_text = build_template(data["text"])

            for cid in CHANNEL_IDS:
                try:
                    if data["type"] == "text":
                        await safe_send_message(context.bot, cid, formatted_text)
                    elif data["type"] == "photo":
                        await context.bot.send_photo(
                            chat_id=cid,
                            photo=data["file_id"],
                            caption=formatted_text,
                            parse_mode="Markdown"
                        )
                    elif data["type"] == "video":
                        await context.bot.send_video(
                            chat_id=cid,
                            video=data["file_id"],
                            caption=formatted_text,
                            parse_mode="Markdown"
                        )
                except TelegramError as e:
                    print(f"⚠️ Failed to send: {e}")

            await update.message.reply_text("✅ Sent to all channels!")
            del pending_messages[user_id]
            return

        # ❌ Cancel
        elif response.lower() in ["no", "n", "cancel"]:
            await update.message.reply_text("❌ Cancelled.")
            del pending_messages[user_id]
            return

        # ✏️ Edit
        else:
            pending_messages[user_id]["text"] = response
            formatted_preview = build_template(response)
            await update.message.reply_text(
                f"✏️ Updated text preview:\n\n{formatted_preview}\n\nNow reply 'Yes' to send.",
                parse_mode="Markdown",
                disable_web_page_preview=True
            )
            return

    # === NEW MESSAGE HANDLING ===
    translated_text = translator.translate(text) if text else ""

    if photo:
        file_id = photo[-1].file_id
        pending_messages[user_id] = {
            "type": "photo", "file_id": file_id, "text": translated_text, "time": time.time()
        }
        preview = build_template(translated_text)
        await update.message.reply_photo(
            photo=file_id, caption=f"{preview}\n\nSend to channel? (Yes / No)", parse_mode="Markdown"
        )
    elif video:
        file_id = video.file_id
        pending_messages[user_id] = {
            "type": "video", "file_id": file_id, "text": translated_text, "time": time.time()
        }
        preview = build_template(translated_text)
        await update.message.reply_video(
            video=file_id, caption=f"{preview}\n\nSend to channel? (Yes / No)", parse_mode="Markdown"
        )
    elif text:
        pending_messages[user_id] = {
            "type": "text", "text": translated_text, "time": time.time()
        }
        preview = build_template(translated_text)
        await update.message.reply_text(
            f"{preview}\n\nSend to channel? (Yes / No)",
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
    else:
        await update.message.reply_text("⚠️ Please send text, image, or video.")


# === RUN BOT ===
async def run_bot():
    app_tg = ApplicationBuilder().token(BOT_TOKEN).build()
    app_tg.add_handler(CommandHandler("start", start))
    app_tg.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO, handle_message))

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
