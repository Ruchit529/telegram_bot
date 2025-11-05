import os
import asyncio
import threading
import time
import requests
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from deep_translator import GoogleTranslator
from telegram.error import TelegramError
from html import escape

# === CONFIGURATION ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_IDS = ["-1003052492544", "-1003238213356"]
ALLOWED_USERS = [7173549132]
SELF_URL = os.getenv("SELF_URL", "https://telegram_bot_w8pe.onrender.com")

translator = GoogleTranslator(source="auto", target="en")
pending_messages = {}
MESSAGE_TIMEOUT = 180  # 3 minutes

# === SIMPLE FLASK SERVER ===
app_web = Flask(__name__)

@app_web.route('/')
def home():
    return "✅ Telegram bot is running on Render!", 200

def run_web():
    port = int(os.getenv("PORT", 10000))
    print(f"🌐 Web server running on port {port}")
    app_web.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

def ping_self():
    while True:
        try:
            requests.get(SELF_URL)
        except Exception:
            pass
        time.sleep(300)

# === CLEANUP ===
def cleanup_pending():
    now = time.time()
    expired = [u for u, d in pending_messages.items() if now - d["time"] > MESSAGE_TIMEOUT]
    for u in expired:
        del pending_messages[u]

# === INLINE BUTTONS ===
def confirm_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes, Send", callback_data="confirm_yes"),
         InlineKeyboardButton("❌ No, Cancel", callback_data="confirm_no")]
    ])

# === MAIN BOT LOGIC ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in ALLOWED_USERS:
        return await update.message.reply_text("🚫 You are not authorized to use this bot.")
    await update.message.reply_text("👋 Send me text, photo, or video — you can even edit your message before confirming!")

async def process_message(msg, context):
    """Process both new and edited messages"""
    cleanup_pending()
    user_id = msg.from_user.id
    if user_id not in ALLOWED_USERS:
        return

    text = msg.caption or msg.text or ""
    text = translator.translate(text) if text else ""
    safe_text = escape(text)

    photo = msg.photo[-1].file_id if msg.photo else None
    video = msg.video.file_id if msg.video else None

    pending_messages[user_id] = {
        "type": "photo" if photo else "video" if video else "text",
        "file_id": photo or video,
        "text": text,
        "time": time.time(),
    }

    preview_text = f"<b>Preview:</b>\n{safe_text}\n\n<b>Send to channel?</b>"

    if photo:
        await msg.reply_photo(photo=photo, caption=preview_text, parse_mode="HTML", reply_markup=confirm_keyboard())
    elif video:
        await msg.reply_video(video=video, caption=preview_text, parse_mode="HTML", reply_markup=confirm_keyboard())
    else:
        await msg.reply_text(preview_text, parse_mode="HTML", reply_markup=confirm_keyboard())

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await process_message(update.message, context)

async def handle_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.edited_message:
        await process_message(update.edited_message, context)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button clicks"""
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    if user_id not in pending_messages:
        return await query.edit_message_caption(caption="⚠️ No pending message or time expired.", parse_mode="HTML")

    data = pending_messages[user_id]

    if query.data == "confirm_yes":
        for cid in CHANNEL_IDS:
            try:
                if data["type"] == "text":
                    await context.bot.send_message(chat_id=cid, text=data["text"], parse_mode="HTML")
                elif data["type"] == "photo":
                    await context.bot.send_photo(chat_id=cid, photo=data["file_id"], caption=data["text"], parse_mode="HTML")
                elif data["type"] == "video":
                    await context.bot.send_video(chat_id=cid, video=data["file_id"], caption=data["text"], parse_mode="HTML")
            except TelegramError as e:
                print(f"⚠️ Error sending to {cid}: {e}")

        await query.edit_message_caption(caption="✅ Message sent to all channels!", parse_mode="HTML")
        del pending_messages[user_id]

    elif query.data == "confirm_no":
        await query.edit_message_caption(caption="❌ Cancelled.", parse_mode="HTML")
        del pending_messages[user_id]

# === RUN BOT ===
async def run_bot():
    app_tg = ApplicationBuilder().token(BOT_TOKEN).build()
    app_tg.add_handler(CommandHandler("start", start))
    app_tg.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO, handle_message))
    app_tg.add_handler(MessageHandler(filters.UpdateType.EDITED_MESSAGE, handle_edit))
    app_tg.add_handler(CallbackQueryHandler(handle_callback))

    print("🚀 Telegram bot running...")
    await app_tg.initialize()
    await app_tg.start()
    await app_tg.updater.start_polling()
    await asyncio.Event().wait()

# === MAIN ===
if __name__ == "__main__":
    threading.Thread(target=run_web).start()
    threading.Thread(target=ping_self, daemon=True).start()
    asyncio.run(run_bot())
