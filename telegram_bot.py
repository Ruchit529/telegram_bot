import os
import asyncio
import threading
import requests
import time
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from googletrans import Translator

# === CONFIGURATION ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
ALLOWED_USERS = [7173549132]  # 👈 replace with your Telegram user ID
CHANNEL_IDS = ["-1003052492544", "-1003238213356"]  # 👈 add your channels here
SELF_URL = os.getenv("SELF_URL", "https://telegram-bot-w8pe.onrender.com")  # 👈 your Render URL

translator = Translator()

# === FLASK WEB SERVER ===
app_web = Flask(__name__)

@app_web.route('/')
def home():
    return "✅ Telegram bot is running on Render!", 200

# === TRANSLATION FUNCTION ===
def translate_text_to_english(text):
    try:
        return translator.translate(text, dest='en').text
    except Exception:
        return text  # fallback if translation fails

# === TELEGRAM HANDLERS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ALLOWED_USERS:
        await update.message.reply_text("🚫 You are not authorized to use this bot.")
        return
    await update.message.reply_text("👋 Hi! Send me any message, photo, or video — I'll ask before posting to all channels.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ALLOWED_USERS:
        await update.message.reply_text("🚫 You are not authorized to use this bot.")
        return

    message = update.message
    context.user_data["pending_message"] = message

    text = message.caption or message.text or ""
    translated = translate_text_to_english(text) if text else ""

    preview_text = f"📝 *Preview (English)*:\n\n{translated}" if translated else "📸 Media without text."
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="confirm_send"),
         InlineKeyboardButton("❌ No", callback_data="cancel_send")]
    ])
    await update.message.reply_text(preview_text, parse_mode="Markdown", reply_markup=keyboard)

async def handle_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    message = context.user_data.get("pending_message")

    if not message:
        await query.edit_message_text("⚠️ No message pending.")
        return

    if query.data == "confirm_send":
        await query.edit_message_text("📤 Sending to channels...")
        bot = Bot(token=BOT_TOKEN)

        text = message.caption or message.text or ""
        translated = translate_text_to_english(text) if text else ""

        sent = False
        for cid in CHANNEL_IDS:
            try:
                if message.text:
                    await bot.send_message(chat_id=cid, text=translated)
                    sent = True
                elif message.photo:
                    photo = message.photo[-1].file_id
                    await bot.send_photo(chat_id=cid, photo=photo, caption=translated or "")
                    sent = True
                elif message.video:
                    video = message.video.file_id
                    await bot.send_video(chat_id=cid, video=video, caption=translated or "")
                    sent = True
            except Exception as e:
                print(f"❌ Failed to send to {cid}: {e}")

        if sent:
            await query.edit_message_text("✅ Sent to all channels!")
        else:
            await query.edit_message_text("⚠️ Unsupported or failed to send.")

    elif query.data == "cancel_send":
        await query.edit_message_text("❌ Cancelled sending.")

# === TELEGRAM BOT RUNNER ===
async def run_bot():
    app_tg = ApplicationBuilder().token(BOT_TOKEN).build()

    app_tg.add_handler(CommandHandler("start", start))
    app_tg.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))
    app_tg.add_handler(CallbackQueryHandler(handle_confirmation))

    print("🚀 Telegram bot is running...")
    await app_tg.run_polling()

# === KEEP-ALIVE SELF PING ===
def self_ping():
    if not SELF_URL:
        print("⚠️ SELF_URL not set, skipping self-ping.")
        return
    while True:
        try:
            requests.get(SELF_URL)
            print(f"🔁 Self-ping successful: {SELF_URL}")
        except Exception as e:
            print(f"⚠️ Ping failed: {e}")
        time.sleep(300)  # every 5 min

# === MAIN ===
if __name__ == "__main__":
    threading.Thread(
        target=lambda: app_web.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)), debug=False, use_reloader=False)
    ).start()
    threading.Thread(target=self_ping, daemon=True).start()
    asyncio.run(run_bot())