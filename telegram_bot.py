import os
import threading
import asyncio
from flask import Flask
from telegram import Update, Bot
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# === Config ===
BOT_TOKEN = os.getenv("BOT_TOKEN") or "YOUR_BOT_TOKEN_HERE"
CHANNEL_IDS = ["-1003052492544"]  # Add your channel IDs

# === Web Server (for Render keep-alive) ===
app_web = Flask(__name__)

@app_web.route('/')
def home():
    return "✅ Telegram bot is running on Render!", 200

def run_web():
    port = int(os.getenv("PORT", 10000))
    print(f"🌐 Starting web server on port {port}")
    app_web.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

# === Telegram Bot Handlers ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hi! Send me any text, photo, or video — I’ll share it to all channels!"
    )

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot = Bot(token=BOT_TOKEN)
    sent = False

    if update.message.text:
        text = update.message.text
        for cid in CHANNEL_IDS:
            await bot.send_message(chat_id=cid, text=text)
        sent = True

    elif update.message.photo:
        photo = update.message.photo[-1].file_id
        caption = update.message.caption or ""
        for cid in CHANNEL_IDS:
            await bot.send_photo(chat_id=cid, photo=photo, caption=caption)
        sent = True

    elif update.message.video:
        video = update.message.video.file_id
        caption = update.message.caption or ""
        for cid in CHANNEL_IDS:
            await bot.send_video(chat_id=cid, video=video, caption=caption)
        sent = True

    if sent:
        await update.message.reply_text("✅ Sent to all channels!")
    else:
        await update.message.reply_text("⚠️ Unsupported message type.")

# === Run Bot (in main thread, async-safe) ===
async def run_bot():
    app_tg = ApplicationBuilder().token(BOT_TOKEN).build()
    app_tg.add_handler(CommandHandler("start", start))
    app_tg.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, broadcast))
    print("🚀 Telegram bot is running...")
    await app_tg.run_polling()

# === Entry Point ===
if __name__ == "__main__":
    threading.Thread(target=run_web).start()
    asyncio.run(run_bot())
