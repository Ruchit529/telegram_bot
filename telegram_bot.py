import os
import asyncio
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

# === Configuration ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

# === Flask App ===
app = Flask(__name__)

# === Telegram Bot Application ===
application = Application.builder().token(BOT_TOKEN).build()

# Example handler
async def start(update: Update, context):
    await update.message.reply_text("✅ Bot is working via webhook!")

application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, start))

# === Flask Route for Webhook ===
@app.route(f"/webhook/{BOT_TOKEN}", methods=["POST"])
async def webhook():
    update = Update.de_json(request.get_json(force=True), application.bot)
    # ✅ FIX: Initialize before processing
    if not application._initialized:
        await application.initialize()
    await application.process_update(update)
    return "OK", 200

# === Root Route for Testing ===
@app.route("/")
def index():
    return "Bot is running with webhook!", 200

# === Set Webhook Automatically ===
async def set_webhook():
    url = f"{WEBHOOK_URL}/webhook/{BOT_TOKEN}"
    await application.bot.set_webhook(url)
    print(f"Webhook set to {url}")

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(set_webhook())
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
