import os
import asyncio
from flask import Flask, request
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    CallbackQueryHandler,
    filters,
)
from googletrans import Translator
from telegram.error import TelegramError

# === CONFIGURATION ===
BOT_TOKEN = os.getenv("BOT_TOKEN") or "8554458574:AAHmpmEOGfjfNTSUDSLp0gBLyDLLEs_IxCM"
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # <-- your Vercel deployment URL, e.g. https://mybot.vercel.app
CHANNEL_IDS = ["-1003052492544", "-1003238213356"]
ALLOWED_USER = 7173549132  # your Telegram user ID

translator = Translator()
pending_messages = {}
application = ApplicationBuilder().token(BOT_TOKEN).build()

# === FLASK APP ===
app = Flask(__name__)

@app.route("/", methods=["GET"])
def home():
    return "✅ Telegram bot webhook running on Vercel!", 200


@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    try:
        update = Update.de_json(request.get_json(force=True), application.bot)
        asyncio.run(application.process_update(update))
    except Exception as e:
        print("❌ Webhook error:", e)
    return "ok", 200


# === HELPERS ===
async def safe_translate(text: str):
    if not text:
        return ""
    result = translator.translate(text, dest="en")
    return result.text


# === HANDLERS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ALLOWED_USER:
        await update.message.reply_text("🚫 You are not authorized to use this bot.")
        return
    await update.message.reply_text(
        "👋 Send text, photo, or video — I’ll translate it and ask before posting."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id != ALLOWED_USER:
        await update.message.reply_text("🚫 You are not authorized.")
        return

    text = update.message.caption or update.message.text
    photo = update.message.photo
    video = update.message.video

    # If waiting for confirmation
    if user_id in pending_messages:
        response = (update.message.text or "").strip().lower()
        data = pending_messages[user_id]

        if response in ["yes", "y", "ok", "send"]:
            for cid in CHANNEL_IDS:
                try:
                    if data["type"] == "text":
                        await context.bot.send_message(chat_id=cid, text=data["text"])
                    elif data["type"] == "photo":
                        await context.bot.send_photo(chat_id=cid, photo=data["file_id"], caption=data["text"])
                    elif data["type"] == "video":
                        await context.bot.send_video(chat_id=cid, video=data["file_id"], caption=data["text"])
                except TelegramError:
                    pass
            await update.message.reply_text("✅ Sent to channels!")
            del pending_messages[user_id]

        elif response in ["no", "n", "cancel"]:
            await update.message.reply_text("❌ Cancelled.")
            del pending_messages[user_id]
        else:
            await update.message.reply_text("Please reply with Yes or No.")
        return

    # Otherwise, process new message
    translated_text = await safe_translate(text)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="yes"),
         InlineKeyboardButton("❌ No", callback_data="no")]
    ])

    if photo:
        file_id = photo[-1].file_id
        pending_messages[user_id] = {"type": "photo", "file_id": file_id, "text": translated_text}
        await update.message.reply_photo(photo=file_id, caption=f"🖼 {translated_text}\n\nSend to channels?", reply_markup=keyboard)
    elif video:
        file_id = video.file_id
        pending_messages[user_id] = {"type": "video", "file_id": file_id, "text": translated_text}
        await update.message.reply_video(video=file_id, caption=f"🎥 {translated_text}\n\nSend to channels?", reply_markup=keyboard)
    elif text:
        pending_messages[user_id] = {"type": "text", "text": translated_text}
        await update.message.reply_text(f"{translated_text}\n\nSend to channels?", reply_markup=keyboard)
    else:
        await update.message.reply_text("⚠️ Send text, photo, or video.")


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if user_id not in pending_messages:
        await query.message.reply_text("❌ No pending message.")
        return
    data = pending_messages[user_id]
    if query.data == "yes":
        for cid in CHANNEL_IDS:
            try:
                if data["type"] == "text":
                    await context.bot.send_message(chat_id=cid, text=data["text"])
                elif data["type"] == "photo":
                    await context.bot.send_photo(chat_id=cid, photo=data["file_id"], caption=data["text"])
                elif data["type"] == "video":
                    await context.bot.send_video(chat_id=cid, video=data["file_id"], caption=data["text"])
            except TelegramError:
                pass
        await query.message.reply_text("✅ Sent to channels!")
    else:
        await query.message.reply_text("❌ Cancelled.")
    del pending_messages[user_id]


# === REGISTER HANDLERS ===
application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO, handle_message))
application.add_handler(CallbackQueryHandler(button_callback))

# === SET WEBHOOK ===
async def set_webhook():
    bot = Bot(token=BOT_TOKEN)
    await bot.set_webhook(f"{WEBHOOK_URL}/{BOT_TOKEN}")
    print(f"✅ Webhook set to {WEBHOOK_URL}/{BOT_TOKEN}")

asyncio.run(set_webhook())
