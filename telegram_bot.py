import os
import time
import threading
import asyncio
import requests
import re
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

# ===== CONFIG =====
BOT_TOKEN = os.getenv("BOT_TOKEN")

CHANNEL_1 = "-1003052492544"
CHANNEL_2 = "-1003238213356"

ALLOWED_USERS = {7173549132, 7050803817}

SELF_URL = os.getenv("SELF_URL", "")

translator = GoogleTranslator(source="auto", target="en")

pending_messages = {}

# ===== TEMPLATE SETTINGS =====
template_settings = {
    "title": "Crunchyroll Premium Account 👇",
    "channels": [
        "@free_crunchyroll_account_4u",
        "@Crunchyroll_Anime_Chatt",
        "@crunchyroll_account_free_chatt"
    ],
    "show_numbers": True
}

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

# ===== LINK EXTRACT =====
def extract_links(text):
    if not text:
        return []
    return re.findall(r'(https?://\S+|www\.\S+)', text)

# ===== TEMPLATE BUILDER =====
def build_template(text):

    links = extract_links(text)

    clean_text = text
    for link in links:
        clean_text = clean_text.replace(link, "").strip()

    result = "👇👇👇\n\n"
    result += f"{template_settings['title']}\n\n"

    for i, link in enumerate(links, start=1):
        if template_settings["show_numbers"]:
            result += f"{i}. {link}\n\n"
        else:
            result += f"{link}\n\n"

    result += "\nJoin Backup Channels 👇\n\n"

    for ch in template_settings["channels"]:
        result += f"👉 {ch}\n"

    return result.strip()

# ===== START =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in ALLOWED_USERS:
        return
    await update.message.reply_text("Send anything to create post.")

# ===== HANDLE MESSAGE =====
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.message.from_user.id
    if user_id not in ALLOWED_USERS:
        return

    text = update.message.text or update.message.caption or ""

    try:
        translated = await asyncio.to_thread(translator.translate, text)
    except:
        translated = text

    data = {
        "text": translated,
        "type": "text"
    }

    if update.message.photo:
        data["type"] = "photo"
        data["file_id"] = update.message.photo[-1].file_id

        await update.message.reply_photo(
            photo=data["file_id"],
            caption=build_template(translated),
            parse_mode="Markdown"
        )

    elif update.message.video:
        data["type"] = "video"
        data["file_id"] = update.message.video.file_id

        await update.message.reply_video(
            video=data["file_id"],
            caption=build_template(translated),
            parse_mode="Markdown"
        )

    else:
        await update.message.reply_text(
            build_template(translated),
            parse_mode="Markdown"
        )

    pending_messages[user_id] = data

# ===== SEND POST =====
async def send_post(context, cid, data):

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

        else:
            await context.bot.send_video(
                chat_id=cid,
                video=data["file_id"],
                caption=build_template(data["text"]),
                parse_mode="Markdown"
            )

    except:
        pass

# ===== COMMANDS =====

async def set_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    template_settings["title"] = " ".join(context.args)
    await update.message.reply_text("✅ Title updated")

async def add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ch = context.args[0]
    template_settings["channels"].append(ch)
    await update.message.reply_text("✅ Channel added")

async def remove_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ch = context.args[0]
    if ch in template_settings["channels"]:
        template_settings["channels"].remove(ch)
        await update.message.reply_text("✅ Channel removed")

async def toggle_numbers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    template_settings["show_numbers"] = not template_settings["show_numbers"]
    await update.message.reply_text("🔢 Numbering toggled")

# ===== RUN BOT =====
def run_bot():

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("settitle", set_title))
    app.add_handler(CommandHandler("addchannel", add_channel))
    app.add_handler(CommandHandler("removechannel", remove_channel))
    app.add_handler(CommandHandler("numbers", toggle_numbers))

    app.add_handler(MessageHandler(filters.ALL, handle_message))

    print("Bot running...")
    app.run_polling()

# ===== MAIN =====
if __name__ == "__main__":

    threading.Thread(target=run_web).start()
    threading.Thread(target=ping_self, daemon=True).start()

    run_bot()
