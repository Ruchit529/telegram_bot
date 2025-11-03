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

# === CONFIGURATION ===
BOT_TOKEN = os.getenv("BOT_TOKEN") or "YOUR_BOT_TOKEN_HERE"
CHANNEL_IDS = ["-1003052492544"]  # Add more if needed
ALLOWED_USERS = [7173549132]  # Replace with your own Telegram ID

# === FLASK SERVER (for Render ping) ===
app_web = Flask(__name__)

@app_web.route('/')
def home():
    return "✅ Telegram bot is running on Render!", 200

def run_web():
    port = int(os.getenv("PORT", 10000))
    print(f"🌐 Web server running on port {port}")
    app_web.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

# === TELEGRAM BOT ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in ALLOWED_USERS:
        await update.message.reply_text("🚫 Sorry, you are not authorized to use this bot.")
        return
    await update.message.reply_text("👋 Hi! Send me any message, photo, or video — I’ll post it to your channels.")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot = Bot(token=BOT_TOKEN)
    user_id = update.message.from_user.id

    # Restrict unauthorized users
    if user_id not in ALLOWED_USERS:
        await update.message.reply_text("🚫 You are not authorized to use this bot.")
        return

    sent = False

    if update.message.text:
        for cid in CHANNEL_IDS:
            await bot.send_message(chat_id=cid, text=update.message.text)
        sent = True

    elif update.message.photo:
        photo = update.message.photo[-1].file_id
        for cid in CHANNEL_IDS:
            await bot.send_photo(chat_id=cid, photo=photo, caption=update.message.caption or "")
        sent = True

    elif update.message.video:
        video = update.message.video.file_id
        for cid in CHANNEL_IDS:
            await bot.send_video(chat_id=cid, video=video, caption=update.message.caption or "")
        sent = True

    if sent:
        await update.message.reply_text("✅ Sent to all channels!")
    else:
        await update.message.reply_text("⚠️ Unsupported message type.")

# === BOT RUNNER ===
async def run_bot():
    app_tg = ApplicationBuilder().token(BOT_TOKEN).build()
    app_tg.add_handler(CommandHandler("start", start))
    app_tg.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, broadcast))

    print("🚀 Telegram bot is running...")
    await app_tg.initialize()
    await app_tg.start()
    await app_tg.updater.start_polling()
    await asyncio.Event().wait()  # Keeps bot running forever

if __name__ == "__main__":
    threading.Thread(target=run_web).start()
    asyncio.run(run_bot())