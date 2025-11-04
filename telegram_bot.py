import os
import asyncio
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

# === CONFIGURATION ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_IDS = ["-1003052492544", "-1003238213356"]  # Your channel IDs
ALLOWED_USERS = [7173549132]  # ✅ Replace with your Telegram user ID
SELF_URL = os.getenv("SELF_URL", "https://telegram_bot_w8pe.onrender.com")  # ⚠️ Replace with your Render URL

# === FLASK APP FOR RENDER PING ===
app = Flask(__name__)

@app.route('/')
def home():
    return "✅ Bot is alive"

def keep_alive():
    async def ping():
        while True:
            try:
                requests.get(SELF_URL)  # <-- Replace with your Render URL
            except Exception as e:
                print("Ping error:", e)
            await asyncio.sleep(300)  # ping every 5 minutes

    asyncio.create_task(ping())

# === TELEGRAM BOT HANDLERS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ALLOWED_USERS:
        return await update.message.reply_text("🚫 You are not allowed to use this bot.")
    await update.message.reply_text("✅ Bot is running! Send me a message to forward.")

# Pending messages before confirmation
pending_messages = {}

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ALLOWED_USERS:
        return await update.message.reply_text("🚫 You are not allowed to use this bot.")

    text = update.message.text or "(media message)"
    preview = f"📝 *Preview:*\n{text}\n\nSend to channels? (yes/no)"
    await update.message.reply_markdown(preview)
    pending_messages[user_id] = text

async def confirm_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in pending_messages:
        return await update.message.reply_text("No pending message found.")

    reply = update.message.text.lower()
    if reply == "yes":
        text = pending_messages.pop(user_id)
        for cid in CHANNEL_IDS:
            try:
                await context.bot.send_message(chat_id=cid, text=text)
            except Exception as e:
                print("Send error:", e)
        await update.message.reply_text("✅ Sent to channel(s).")
    elif reply == "no":
        pending_messages.pop(user_id)
        await update.message.reply_text("❌ Message discarded.")
    else:
        await update.message.reply_text("Please reply with 'yes' or 'no'.")

# === RUN BOT ===
async def run_bot():
    app_tg = ApplicationBuilder().token(BOT_TOKEN).build()
    app_tg.add_handler(CommandHandler("start", start))
    app_tg.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app_tg.add_handler(MessageHandler(filters.Regex("^(?i)(yes|no)$"), confirm_send))

    print("🚀 Telegram bot is running...")
    keep_alive()
    await app_tg.run_polling()

if __name__ == "__main__":
    asyncio.run(run_bot())
