import os
from flask import Flask, request
from telegram import Bot, Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
import asyncio

# === CONFIGURATION ===
BOT_TOKEN = os.getenv("BOT_TOKEN") or "8554458574:AAHmpmEOGfjfNTSUDSLp0gBLyDLLEs_IxCM"
CHANNEL_IDS = ["-1003052492544","-1003238213356"]  # add more if needed
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # e.g. https://yourapp.onrender.com

app_web = Flask(__name__)

# === TELEGRAM LOGIC ===
bot = Bot(token=BOT_TOKEN)
application = Application.builder().token(BOT_TOKEN).build()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hi! Send me any message, photo, or video — I’ll post it to all channels."
    )


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
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


application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, broadcast))


# === FLASK WEBHOOK ENDPOINT ===
@app_web.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    asyncio.run(application.process_update(update))
    return "OK", 200


@app_web.route("/")
def home():
    return "✅ Telegram bot webhook is active!", 200


# === STARTUP ===
async def set_webhook():
    await bot.delete_webhook()
    await bot.set_webhook(url=f"{WEBHOOK_URL}/{BOT_TOKEN}")
    print(f"🌐 Webhook set to {WEBHOOK_URL}/{BOT_TOKEN}")


if __name__ == "__main__":
    print("🚀 Starting Telegram bot webhook mode...")
    asyncio.run(set_webhook())
    port = int(os.getenv("PORT", 10000))
    app_web.run(host="0.0.0.0", port=port)
