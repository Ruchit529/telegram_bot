import os
import time
import threading
import asyncio
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

# ===== CONFIG =====
BOT_TOKEN = os.getenv("BOT_TOKEN")

CHANNEL_1 = "-1003052492544"
CHANNEL_2 = "-1003238213356"

ALLOWED_USERS = {7173549132, 7050803817}

SELF_URL = os.getenv("SELF_URL", "")

translator = GoogleTranslator(source="auto", target="en")

pending_messages = {}

# toggles
silent_mode = {}
button_mode = {}

# dynamic channels
channel_links = [
    "@free_crunchyroll_account_4u",
    "@Crunchyroll_Anime_Chatt"
]

MESSAGE_TIMEOUT = 600


# ===== FLASK SERVER =====
app_web = Flask(__name__)

@app_web.route("/")
def home():
    return "Bot Alive", 200


def run_web():
    port = int(os.getenv("PORT", 10000))
    app_web.run(host="0.0.0.0", port=port)


# ===== KEEP ALIVE =====
session = requests.Session()

def ping_self():
    if not SELF_URL:
        return
    while True:
        try:
            session.get(SELF_URL, timeout=10)
        except:
            pass
        time.sleep(300)


# ===== CLEANUP =====
def cleanup_pending():
    now = time.time()
    expired = [
        uid for uid, data in pending_messages.items()
        if now - data["time"] > MESSAGE_TIMEOUT
    ]
    for uid in expired:
        pending_messages.pop(uid, None)


# ===== TEMPLATE =====
def build_template(text):
    result = f"👇👇👇\n\n{text or ''}\n\n"

    if channel_links:
        result += "Join Backup Channel 👇\n\n"
        for ch in channel_links:
            result += f"👉 {ch}\n"

    return result.strip()


# ===== BUTTON MARKUP =====
def post_button(buttons):
    if not buttons:
        return None

    keyboard = []
    for btn in buttons:
        keyboard.append([InlineKeyboardButton(btn["name"], url=btn["link"])])

    return InlineKeyboardMarkup(keyboard)


# ===== PREVIEW BUTTONS =====
def buttons(user_id):

    silent = silent_mode.get(user_id, False)

    notify_text = "🔕 Silent Mode ON" if silent else "🔔 Silent Mode OFF"

    keyboard = [
        [InlineKeyboardButton(notify_text, callback_data="toggle_notify")],
        [InlineKeyboardButton("➕ Add Button", callback_data="add_button")],
        [InlineKeyboardButton("✏ Edit Caption", callback_data="edit")],
        [
            InlineKeyboardButton("🎮 Vanced Games", callback_data="vanced"),
            InlineKeyboardButton("🍿 Crunchyroll Anime", callback_data="crunchy"),
        ],
        [InlineKeyboardButton("🚀 Send to Both", callback_data="both")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
    ]

    return InlineKeyboardMarkup(keyboard)


# ===== TRANSLATION =====
async def translate_text(text):
    if not text:
        return ""
    try:
        return await asyncio.to_thread(translator.translate, text)
    except:
        return text


# ===== START =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.message.from_user.id
    if user_id not in ALLOWED_USERS:
        return

    await update.message.reply_text("Send text/photo/video to create post.")


# ===== HANDLE MESSAGE =====
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    cleanup_pending()

    user_id = update.message.from_user.id
    if user_id not in ALLOWED_USERS:
        return

    # ===== BUTTON CREATION FLOW =====
    if user_id in pending_messages:

        data = pending_messages[user_id]

        if data.get("adding_button"):

            if data.get("step") == "name":
                data["temp_name"] = update.message.text
                data["step"] = "link"

                await update.message.reply_text("Now send button link.")
                return

            elif data.get("step") == "link":
                data["buttons"].append({
                    "name": data["temp_name"],
                    "link": update.message.text
                })

                data["adding_button"] = False
                data["step"] = None

                await update.message.reply_text(
                    "✅ Button added! Click 'Add Button' again for more.",
                    reply_markup=buttons(user_id)
                )
                return

    # ===== EDIT MODE =====
    if context.user_data.get("editing"):

        translated = await translate_text(update.message.text)

        if user_id in pending_messages:
            pending_messages[user_id]["text"] = translated

            await update.message.reply_text(
                build_template(translated),
                reply_markup=buttons(user_id)
            )

        context.user_data["editing"] = False
        return


    text = update.message.caption or update.message.text
    photo = update.message.photo
    video = update.message.video

    translated = await translate_text(text)

    data = {
        "text": translated,
        "time": time.time(),
        "buttons": [],
        "adding_button": False,
        "step": None
    }

    if photo:

        data.update(type="photo", file_id=photo[-1].file_id)

        await update.message.reply_photo(
            photo=data["file_id"],
            caption=build_template(translated),
            reply_markup=buttons(user_id)
        )

    elif video:

        data.update(type="video", file_id=video.file_id)

        await update.message.reply_video(
            video=data["file_id"],
            caption=build_template(translated),
            reply_markup=buttons(user_id)
        )

    else:

        data.update(type="text")

        await update.message.reply_text(
            build_template(translated),
            reply_markup=buttons(user_id)
        )

    pending_messages[user_id] = data


# ===== SEND POST =====
async def send_post(context, cid, data, silent):

    markup = post_button(data.get("buttons"))

    try:

        if data["type"] == "text":
            await context.bot.send_message(
                chat_id=cid,
                text=build_template(data["text"]),
                disable_web_page_preview=True,
                disable_notification=silent,
                reply_markup=markup
            )

        elif data["type"] == "photo":
            await context.bot.send_photo(
                chat_id=cid,
                photo=data["file_id"],
                caption=build_template(data["text"]),
                disable_notification=silent,
                reply_markup=markup
            )

        else:
            await context.bot.send_video(
                chat_id=cid,
                video=data["file_id"],
                caption=build_template(data["text"]),
                disable_notification=silent,
                reply_markup=markup
            )

    except TelegramError:
        pass


# ===== BUTTON HANDLER =====
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    if user_id not in pending_messages:
        await query.message.delete()
        return

    data = pending_messages[user_id]

    if query.data == "toggle_notify":
        silent_mode[user_id] = not silent_mode.get(user_id, False)
        await query.edit_message_reply_markup(reply_markup=buttons(user_id))
        return

    if query.data == "add_button":
        data["adding_button"] = True
        data["step"] = "name"
        await query.message.reply_text("Send button name.")
        return

    if query.data == "edit":
        context.user_data["editing"] = True
        await query.message.reply_text("Send new caption.")
        return

    if query.data == "cancel":
        pending_messages.pop(user_id, None)
        await query.message.delete()
        return

    if query.data == "vanced":
        channels = [CHANNEL_1]
    elif query.data == "crunchy":
        channels = [CHANNEL_2]
    else:
        channels = [CHANNEL_1, CHANNEL_2]

    silent = silent_mode.get(user_id, False)

    for cid in channels:
        await send_post(context, cid, data, silent)

    pending_messages.pop(user_id, None)
    await query.message.delete()


# ===== RUN BOT =====
def run_bot():

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    app.add_handler(
        MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO, handle_message)
    )

    app.add_handler(CallbackQueryHandler(button_handler))

    print("Bot running...")
    app.run_polling()


# ===== MAIN =====
if __name__ == "__main__":

    threading.Thread(target=run_web).start()
    threading.Thread(target=ping_self, daemon=True).start()

    run_bot()
