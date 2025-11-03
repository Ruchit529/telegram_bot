import os
import asyncio
import threading
from flask import Flask
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from googletrans import Translator

# === CONFIGURATION ===
BOT_TOKEN = os.getenv("BOT_TOKEN") or "YOUR_BOT_TOKEN_HERE"

# Replace with your Telegram user ID so only you can use it
ALLOWED_USER_ID = 7173549132

# Add your channel IDs here
CHANNEL_IDS = ["-1003052492544","1003238213356"]

translator = Translator()
pending_messages = {}

# === SIMPLE FLASK WEB SERVER (for Render uptime) ===
app_web = Flask(__name__)

@app_web.route('/')
def home():
    return "✅ Telegram bot is running on Render!", 200


def run_web():
    port = int(os.getenv("PORT", 10000))
    print(f"🌐 Web server running on port {port}")
    app_web.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


# === TELEGRAM BOT LOGIC ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ALLOWED_USER_ID:
        return await update.message.reply_text("❌ You are not authorized to use this bot.")
    await update.message.reply_text("👋 Send text, photo, or video — I’ll translate it to English and ask before posting to channels.")


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ALLOWED_USER_ID:
        return await update.message.reply_text("❌ You are not authorized to use this bot.")

    user_id = update.message.from_user.id
    bot = Bot(token=BOT_TOKEN)
    translated_text = ""

    if update.message.text:
        try:
            translated_text = translator.translate(update.message.text, dest='en').text
        except Exception as e:
            translated_text = update.message.text
        pending_messages[user_id] = {"type": "text", "data": translated_text}
        await update.message.reply_text(
            f"📝 Translated to English:\n\n{translated_text}\n\nSend ✅ 'yes' to post or ❌ 'no' to cancel."
        )

    elif update.message.photo:
        file_id = update.message.photo[-1].file_id
        caption = update.message.caption or ""
        try:
            caption = translator.translate(caption, dest='en').text
        except:
            pass
        pending_messages[user_id] = {"type": "photo", "data": file_id, "caption": caption}
        await update.message.reply_text(
            f"🖼️ Image ready with caption:\n\n{caption}\n\nSend ✅ 'yes' to post or ❌ 'no' to cancel."
        )

    elif update.message.video:
        file_id = update.message.video.file_id
        caption = update.message.caption or ""
        try:
            caption = translator.translate(caption, dest='en').text
        except:
            pass
        pending_messages[user_id] = {"type": "video", "data": file_id, "caption": caption}
        await update.message.reply_text(
            f"🎥 Video ready with caption:\n\n{caption}\n\nSend ✅ 'yes' to post or ❌ 'no' to cancel."
        )
    else:
        await update.message.reply_text("⚠️ Unsupported message type.")


async def confirm_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ALLOWED_USER_ID:
        return

    user_id = update.message.from_user.id
    text = update.message.text.lower().strip()

    if user_id not in pending_messages:
        return

    msg = pending_messages[user_id]

    if text in ["yes", "y", "ok", "send", "✅"]:
        bot = Bot(token=BOT_TOKEN)
        for cid in CHANNEL_IDS:
            if msg["type"] == "text":
                await bot.send_message(chat_id=cid, text=msg["data"])
            elif msg["type"] == "photo":
                await bot.send_photo(chat_id=cid, photo=msg["data"], caption=msg["caption"])
            elif msg["type"] == "video":
                await bot.send_video(chat_id=cid, video=msg["data"], caption=msg["caption"])
        await update.message.reply_text("✅ Sent to all channels!")
        del pending_messages[user_id]

    elif text in ["no", "n", "cancel", "❌"]:
        await update.message.reply_text("🚫 Message cancelled.")
        del pending_messages[user_id]


# === BOT RUNNER ===
async def run_bot():
    app_tg = ApplicationBuilder().token(BOT_TOKEN).build()
    app_tg.add_handler(CommandHandler("start", start))
    app_tg.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, broadcast))
    app_tg.add_handler(MessageHandler(filters.TEXT & filters.ALL, confirm_send))

    print("🚀 Telegram bot is running...")
    await app_tg.initialize()
    await app_tg.start()
    await app_tg.updater.start_polling()
    await asyncio.Event().wait()  # Keeps bot running forever


if __name__ == "__main__":
    threading.Thread(target=run_web).start()
    asyncio.run(run_bot())
