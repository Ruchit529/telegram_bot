import os
import asyncio
import threading
import time
import requests
from flask import Flask
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from deep_translator import GoogleTranslator
from telegram.constants import ParseMode
from telegram.error import TelegramError

# === CONFIGURATION ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_IDS = ["-1003052492544", "-1003238213356"]
ALLOWED_USERS = [7173549132]
SELF_URL = os.getenv("SELF_URL", "https://telegram_bot_w8pe.onrender.com")

translator = GoogleTranslator(source="auto", target="en")
pending_messages = {}
MESSAGE_TIMEOUT = 120


# === FLASK WEB SERVER ===
app_web = Flask(__name__)

@app_web.route('/')
def home():
    return "✅ Telegram bot is running on Render!", 200

def run_web():
    port = int(os.getenv("PORT", 10000))
    print(f"🌐 Web server running on port {port}")
    app_web.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


# === KEEP ALIVE ===
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
    for uid in list(pending_messages.keys()):
        if now - pending_messages[uid]["time"] > MESSAGE_TIMEOUT:
            del pending_messages[uid]


# === BOT COMMANDS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ALLOWED_USERS:
        return await update.message.reply_text("🚫 You are not authorized to use this bot.")
    await update.message.reply_text("👋 Hi! Send me text, photo, or video — I’ll translate and preview before posting.")


# === HANDLE MESSAGES ===
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cleanup_pending()
    user_id = update.message.from_user.id
    if user_id not in ALLOWED_USERS:
        return await update.message.reply_text("🚫 You are not authorized.")

    text = update.message.caption or update.message.text
    photo = update.message.photo
    video = update.message.video
    translated_text = translator.translate(text) if text else ""

    # store message data
    if photo:
        file_id = photo[-1].file_id
        sent = await update.message.reply_photo(
            photo=file_id,
            caption=f"*{translated_text}*\n\n✅ Send / ✏️ Edit / ❌ Cancel?",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Send", callback_data="send")],
                [InlineKeyboardButton("✏️ Edit", callback_data="edit")],
                [InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
            ]),
        )
        pending_messages[user_id] = {
            "type": "photo", "file_id": file_id, "text": translated_text,
            "msg_id": sent.message_id, "chat_id": sent.chat.id, "time": time.time()
        }

    elif video:
        file_id = video.file_id
        sent = await update.message.reply_video(
            video=file_id,
            caption=f"*{translated_text}*\n\n✅ Send / ✏️ Edit / ❌ Cancel?",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Send", callback_data="send")],
                [InlineKeyboardButton("✏️ Edit", callback_data="edit")],
                [InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
            ]),
        )
        pending_messages[user_id] = {
            "type": "video", "file_id": file_id, "text": translated_text,
            "msg_id": sent.message_id, "chat_id": sent.chat.id, "time": time.time()
        }

    elif text:
        sent = await update.message.reply_text(
            f"*{translated_text}*\n\n✅ Send / ✏️ Edit / ❌ Cancel?",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Send", callback_data="send")],
                [InlineKeyboardButton("✏️ Edit", callback_data="edit")],
                [InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
            ]),
        )
        pending_messages[user_id] = {
            "type": "text", "text": translated_text,
            "msg_id": sent.message_id, "chat_id": sent.chat.id, "time": time.time()
        }


# === HANDLE INLINE BUTTONS ===
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    if user_id not in pending_messages:
        return await query.edit_message_text("⚠️ No pending message found.")

    data = pending_messages[user_id]

    if query.data == "cancel":
        await query.edit_message_text("❌ Cancelled.")
        del pending_messages[user_id]

    elif query.data == "send":
        for cid in CHANNEL_IDS:
            try:
                if data["type"] == "text":
                    await context.bot.send_message(chat_id=cid, text=data["text"], parse_mode=ParseMode.MARKDOWN)
                elif data["type"] == "photo":
                    await context.bot.send_photo(chat_id=cid, photo=data["file_id"], caption=data["text"], parse_mode=ParseMode.MARKDOWN)
                elif data["type"] == "video":
                    await context.bot.send_video(chat_id=cid, video=data["file_id"], caption=data["text"], parse_mode=ParseMode.MARKDOWN)
            except TelegramError:
                pass
        await query.edit_message_text("✅ Sent to all channels!")
        del pending_messages[user_id]

    elif query.data == "edit":
        await query.edit_message_text("✏️ Please send your *new text or caption* below:", parse_mode=ParseMode.MARKDOWN)
        pending_messages[user_id]["await_edit"] = True


# === HANDLE EDIT TEXT ===
async def handle_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in pending_messages or not pending_messages[user_id].get("await_edit"):
        return

    new_text = update.message.text
    data = pending_messages[user_id]
    data["text"] = new_text
    data["await_edit"] = False

    # Edit the original preview message instead of resending
    try:
        await context.bot.edit_message_caption(
            chat_id=data["chat_id"],
            message_id=data["msg_id"],
            caption=f"*{new_text}*\n\n✅ Send / ✏️ Edit / ❌ Cancel?",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Send", callback_data="send")],
                [InlineKeyboardButton("✏️ Edit", callback_data="edit")],
                [InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
            ]),
        )
    except TelegramError:
        await context.bot.edit_message_text(
            chat_id=data["chat_id"],
            message_id=data["msg_id"],
            text=f"*{new_text}*\n\n✅ Send / ✏️ Edit / ❌ Cancel?",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Send", callback_data="send")],
                [InlineKeyboardButton("✏️ Edit", callback_data="edit")],
                [InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
            ]),
        )

    await update.message.reply_text("✅ Text updated!")


# === MAIN RUNNER ===
async def run_bot():
    app_tg = ApplicationBuilder().token(BOT_TOKEN).build()
    app_tg.add_handler(CommandHandler("start", start))
    app_tg.add_handler(CallbackQueryHandler(button_handler))
    app_tg.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit))
    app_tg.add_handler(MessageHandler(filters.ALL, handle_message))

    print("🚀 Telegram bot is running...")
    await app_tg.initialize()
    await app_tg.start()
    await app_tg.updater.start_polling()
    await asyncio.Event().wait()


if __name__ == "__main__":
    threading.Thread(target=run_web).start()
    threading.Thread(target=ping_self, daemon=True).start()
    asyncio.run(run_bot())
