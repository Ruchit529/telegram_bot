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
    ContextTypes,
    CallbackQueryHandler,
    filters,
)
from deep_translator import GoogleTranslator
from telegram.error import TelegramError


# === CONFIGURATION ===
BOT_TOKEN = os.getenv("BOT_TOKEN")

CHANNEL_1 = "-1003052492544"
CHANNEL_2 = "-1003238213356"

ALLOWED_USERS = [7173549132]

SELF_URL = os.getenv("SELF_URL", "https://telegram_bot_w8pe.onrender.com")

GROUP_LINK = "https://t.me/steam_games_chatt"

translator = GoogleTranslator(source="auto", target="en")

pending_messages = {}
MESSAGE_TIMEOUT = 600


# === FLASK SERVER ===
app_web = Flask(__name__)

@app_web.route('/')
def home():
    return "Bot running", 200


def run_web():
    port = int(os.getenv("PORT", 10000))
    app_web.run(host="0.0.0.0", port=port)


# === KEEP ALIVE ===
def ping_self():
    while True:
        try:
            requests.get(SELF_URL)
        except:
            pass
        time.sleep(300)


# === CLEANUP ===
def cleanup_pending():
    now = time.time()

    expired = [
        uid for uid, data in pending_messages.items()
        if now - data["time"] > MESSAGE_TIMEOUT
    ]

    for uid in expired:
        del pending_messages[uid]


# === TEMPLATE ===
def build_template(text):

    if not text:
        text = ""

    return f"👇👇👇\n\n{text}\n\n👉 [JOIN GROUP]({GROUP_LINK})"


# === BUTTONS ===
def get_buttons():

    keyboard = [
        [InlineKeyboardButton("✏ Edit Caption", callback_data="edit")],
        [
            InlineKeyboardButton("🎮 Vanced Games", callback_data="vanced"),
            InlineKeyboardButton("🍿 Crunchyroll Anime", callback_data="crunchy"),
        ],
        [InlineKeyboardButton("🚀 Send to Both", callback_data="both")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
    ]

    return InlineKeyboardMarkup(keyboard)


# === START ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.message.from_user.id not in ALLOWED_USERS:
        return

    await update.message.reply_text(
        "Send text, image, or video.\nPreview will appear with buttons."
    )


# === HANDLE MESSAGE ===
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    cleanup_pending()

    user_id = update.message.from_user.id

    if user_id not in ALLOWED_USERS:
        return

    # === Editing caption ===
    if context.user_data.get("editing"):

        if user_id in pending_messages:

            pending_messages[user_id]["text"] = translator.translate(update.message.text)

            data = pending_messages[user_id]

            await update.message.reply_text(
                build_template(data["text"]),
                parse_mode="Markdown",
                reply_markup=get_buttons()
            )

        context.user_data["editing"] = False
        return


    text = update.message.caption or update.message.text
    photo = update.message.photo
    video = update.message.video

    if text:
        try:
            translated = translator.translate(text)
        except:
            translated = text
    else:
        translated = ""


    # === PHOTO ===
    if photo:

        file_id = photo[-1].file_id

        pending_messages[user_id] = {
            "type": "photo",
            "file_id": file_id,
            "text": translated,
            "time": time.time()
        }

        await update.message.reply_photo(
            photo=file_id,
            caption=build_template(translated),
            parse_mode="Markdown",
            reply_markup=get_buttons()
        )


    # === VIDEO ===
    elif video:

        file_id = video.file_id

        pending_messages[user_id] = {
            "type": "video",
            "file_id": file_id,
            "text": translated,
            "time": time.time()
        }

        await update.message.reply_video(
            video=file_id,
            caption=build_template(translated),
            parse_mode="Markdown",
            reply_markup=get_buttons()
        )


    # === TEXT ===
    elif text:

        pending_messages[user_id] = {
            "type": "text",
            "text": translated,
            "time": time.time()
        }

        await update.message.reply_text(
            build_template(translated),
            parse_mode="Markdown",
            reply_markup=get_buttons()
        )


# === BUTTON HANDLER ===
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    if user_id not in pending_messages:
        await query.edit_message_text("Message expired.")
        return

    data = pending_messages[user_id]

    # === EDIT ===
    if query.data == "edit":

        context.user_data["editing"] = True

        await query.message.reply_text(
            "Send the new caption now."
        )
        return


    # === CANCEL ===
    if query.data == "cancel":

        del pending_messages[user_id]

        await query.edit_message_text("Cancelled.")
        return


    # === CHANNEL SELECTION ===
    channels = []

    if query.data == "vanced":
        channels = [CHANNEL_1]

    elif query.data == "crunchy":
        channels = [CHANNEL_2]

    elif query.data == "both":
        channels = [CHANNEL_1, CHANNEL_2]


    # === SEND POST ===
    for cid in channels:

        try:

            if data["type"] == "text":

                await context.bot.send_message(
                    chat_id=cid,
                    text=build_template(data["text"]),
                    parse_mode="Markdown",
                    disable_web_page_preview=True
                )

            elif data["type"] == "photo":

                await context.bot.send_photo(
                    chat_id=cid,
                    photo=data["file_id"],
                    caption=build_template(data["text"]),
                    parse_mode="Markdown"
                )

            elif data["type"] == "video":

                await context.bot.send_video(
                    chat_id=cid,
                    video=data["file_id"],
                    caption=build_template(data["text"]),
                    parse_mode="Markdown"
                )

        except TelegramError:
            pass


    del pending_messages[user_id]

    await query.edit_message_text("✅ Post sent successfully!")


# === BOT RUNNER ===
async def run_bot():

    app_tg = ApplicationBuilder().token(BOT_TOKEN).build()

    app_tg.add_handler(CommandHandler("start", start))

    app_tg.add_handler(MessageHandler(filters.ALL, handle_message))

    app_tg.add_handler(CallbackQueryHandler(button_handler))

    print("Bot started")

    await app_tg.run_polling()


# === MAIN ===
if __name__ == "__main__":

    threading.Thread(target=run_web).start()

    threading.Thread(target=ping_self, daemon=True).start()

    asyncio.run(run_bot())
