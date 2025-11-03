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
from telegram.error import TelegramError

# === CONFIGURATION ===
BOT_TOKEN = os.getenv("BOT_TOKEN") or "YOUR_BOT_TOKEN_HERE"
CHANNEL_IDS = ["-1003052492544", "-1003238213356"]
ALLOWED_USER = 7173549132  # 👈 your Telegram user ID (only you can use the bot)

translator = Translator()
pending_messages = {}

# === FLASK WEB SERVER (Render requirement) ===
app_web = Flask(__name__)

@app_web.route('/')
def home():
    return "✅ Telegram bot is running on Render!", 200


def run_web():
    port = int(os.getenv("PORT", 10000))
    print(f"🌐 Web server running on port {port}")
    app_web.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


# === HELPER ===
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
        "👋 Send text, photo, or video — I’ll translate to English and ask before posting."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id != ALLOWED_USER:
        await update.message.reply_text("🚫 You are not authorized to use this bot.")
        return

    text = update.message.caption or update.message.text
    photo = update.message.photo
    video = update.message.video

    # === Confirmation handling ===
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
            await update.message.reply_text("Please reply with 'Yes' or 'No'.")
        return

    # === New message handling ===
    translated_text = await safe_translate(text)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="yes"),
         InlineKeyboardButton("❌ No", callback_data="no")]
    ])

    if photo:
        file_id = photo[-1].file_id
        pending_messages[user_id] = {"type": "photo", "file_id": file_id, "text": translated_text}
        await update.message.reply_photo(
            photo=file_id,
            caption=f"🖼 {translated_text}\n\nSend to channels?",
            reply_markup=keyboard
        )
    elif video:
        file_id = video.file_id
        pending_messages[user_id] = {"type": "video", "file_id": file_id, "text": translated_text}
        await update.message.reply_video(
            video=file_id,
            caption=f"🎥 {translated_text}\n\nSend to channels?",
            reply_markup=keyboard
        )
    elif text:
        pending_messages[user_id] = {"type": "text", "text": translated_text}
        await update.message.reply_text(f"{translated_text}\n\nSend to channels?", reply_markup=keyboard)
    else:
        await update.message.reply_text("⚠️ Please send text, photo, or video.")


# === BUTTON HANDLER ===
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


# === MAIN BOT RUNNER ===
async def run_bot():
    app_tg = ApplicationBuilder().token(BOT_TOKEN).build()
    app_tg.add_handler(CommandHandler("start", start))
    app_tg.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO, handle_message))
    app_tg.add_handler(MessageHandler(filters.COMMAND, start))
    app_tg.add_handler(MessageHandler(filters.ALL, handle_message))
    app_tg.add_handler(MessageHandler(filters.StatusUpdate.ALL, handle_message))
    app_tg.add_handler(CommandHandler("cancel", start))
    app_tg.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app_tg.add_handler(CommandHandler("button", button_callback))

    print("🤖 Bot started successfully...")
    await app_tg.initialize()
    await app_tg.start()
    await app_tg.updater.start_polling()
    await asyncio.Event().wait()


if __name__ == "__main__":
    threading.Thread(target=run_web).start()
    asyncio.run(run_bot())