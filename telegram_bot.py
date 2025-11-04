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

# === CONFIGURATION ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_IDS = ["-1003052492544", "-1003238213356"]  # Your channel IDs
ALLOWED_USERS = [7173549132]  # ✅ Replace with your Telegram user ID
SELF_URL = os.getenv("SELF_URL", "https://telegram_bot_w8pe.onrender.com")  # ⚠️ Replace with your Render URL

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
        time.sleep(300)  # every 5 minutes


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


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cleanup_pending()  # 🧹 Remove old confirmations
    user_id = update.message.from_user.id

    if user_id not in ALLOWED_USERS:
        return await update.message.reply_text("🚫 You are not authorized to use this bot.")

    text = update.message.caption or update.message.text
    photo = update.message.photo
    video = update.message.video

    # === Handle confirmations ===
    if user_id in pending_messages:
        response = (update.message.text or "").strip()
        data = pending_messages[user_id]

        # --- Confirm Send ---
        if response.lower() in ["yes", "y", "ok", "send"]:
            for cid in CHANNEL_IDS:
                try:
                    if data["type"] == "text":
                        await context.bot.send_message(chat_id=cid, text=data["text"], parse_mode="Markdown")
                    elif data["type"] == "photo":
                        await context.bot.send_photo(chat_id=cid, photo=data["file_id"], caption=data["text"], parse_mode="Markdown")
                    elif data["type"] == "video":
                        await context.bot.send_video(chat_id=cid, video=data["file_id"], caption=data["text"], parse_mode="Markdown")
                except TelegramError:
                    pass

            # ✅ Edit original confirmation message
            if "msg" in data:
                try:
                    await data["msg"].edit_caption("✅ *Sent to all channels!*", parse_mode="Markdown")
                except Exception:
                    await data["msg"].edit_text("✅ *Sent to all channels!*", parse_mode="Markdown")

            del pending_messages[user_id]
            return

        # --- Cancel ---
        elif response.lower() in ["no", "n", "cancel"]:
            if "msg" in data:
                try:
                    await data["msg"].edit_caption("❌ *Cancelled.*", parse_mode="Markdown")
                except Exception:
                    await data["msg"].edit_text("❌ *Cancelled.*", parse_mode="Markdown")
            del pending_messages[user_id]
            return

        # --- Edit Message Text ---
        else:
            data["text"] = response
            if "msg" in data:
                try:
                    await data["msg"].edit_caption(f"{response}\n\n_Send to channel? (Yes / No)_", parse_mode="Markdown")
                except Exception:
                    await data["msg"].edit_text(f"{response}\n\n_Send to channel? (Yes / No)_", parse_mode="Markdown")
            return

    # === NEW MESSAGE ===
    translated_text = translator.translate(text) if text else ""

    sent_msg = None
    if photo:
        file_id = photo[-1].file_id
        sent_msg = await update.message.reply_photo(
            photo=file_id,
            caption=f"{translated_text}\n\n_Send to channel? (Yes / No)_",
            parse_mode="Markdown"
        )
        pending_messages[user_id] = {"type": "photo", "file_id": file_id, "text": translated_text, "msg": sent_msg, "time": time.time()}

    elif video:
        file_id = video.file_id
        sent_msg = await update.message.reply_video(
            video=file_id,
            caption=f"{translated_text}\n\n_Send to channel? (Yes / No)_",
            parse_mode="Markdown"
        )
        pending_messages[user_id] = {"type": "video", "file_id": file_id, "text": translated_text, "msg": sent_msg, "time": time.time()}

    elif text:
        sent_msg = await update.message.reply_text(
            f"{translated_text}\n\n_Send to channel? (Yes / No)_",
            parse_mode="Markdown"
        )
        pending_messages[user_id] = {"type": "text", "text": translated_text, "msg": sent_msg, "time": time.time()}

    else:
        await update.message.reply_text("⚠️ Please send text, image, or video.")


# === BOT RUNNER ===
async def run_bot():
    app_tg = ApplicationBuilder().token(BOT_TOKEN).build()
    app_tg.add_handler(CommandHandler("start", start))
    app_tg.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO, handle_message))

    print("🚀 Telegram bot is running...")
    await app_tg.run_polling(close_loop=False)


# === MAIN ===
if __name__ == "__main__":
    threading.Thread(target=run_web).start()
    threading.Thread(target=ping_self, daemon=True).start()
    asyncio.run(run_bot())
