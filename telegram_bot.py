import os
import asyncio
import threading
import time
import requests
from flask import Flask
from telegram import Update, MessageEntity
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from deep_translator import GoogleTranslator
from telegram.error import TelegramError

# === CONFIGURATION ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_IDS = ["-1003052492544", "-1003238213356"]
ALLOWED_USERS = [7173549132]
SELF_URL = os.getenv("SELF_URL", "https://telegram_bot_w8pe.onrender.com")
GROUP_LINK = "https://t.me/steam_games_chatt"

translator = GoogleTranslator(source="auto", target="en")
pending_messages = {}
MESSAGE_TIMEOUT = 120  # Auto-clear after 2 minutes

# === SIMPLE FLASK WEB SERVER ===
app_web = Flask(__name__)

@app_web.route('/')
def home():
    return "✅ Telegram bot is running on Render!", 200

def run_web():
    port = int(os.getenv("PORT", 10000))
    app_web.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

# === KEEP ALIVE PING ===
def ping_self():
    while True:
        try:
            requests.get(SELF_URL)
            print(f"🔁 Pinged {SELF_URL}")
        except Exception as e:
            print(f"⚠️ Ping failed: {e}")
        time.sleep(300)

# === CLEANUP PENDING ===
def cleanup_pending():
    now = time.time()
    expired = [uid for uid, d in pending_messages.items() if now - d["time"] > MESSAGE_TIMEOUT]
    for uid in expired:
        del pending_messages[uid]

# === TEMPLATE BUILDER USING ENTITIES ONLY ===
def build_template_entities(text: str, entities=None):
    prefix = "👇👇👇\n\n"
    suffix = "\n\n👉 JOIN GROUP"
    full_text = prefix + (text or "") + suffix

    new_entities = []

    # Shift all existing entities by prefix length
    if entities:
        for e in entities:
            new_entities.append(
                MessageEntity(
                    type=e.type,
                    offset=e.offset + len(prefix),
                    length=e.length,
                    url=getattr(e, "url", None),
                    user=getattr(e, "user", None),
                    language=getattr(e, "language", None),
                )
            )

    # Add clickable JOIN GROUP link
    join_offset = len(full_text) - len("JOIN GROUP")
    new_entities.append(
        MessageEntity(type="text_link", offset=join_offset, length=len("JOIN GROUP"), url=GROUP_LINK)
    )

    return full_text, new_entities

# === SAFE SEND FUNCTION ===
async def safe_send(bot, chat_id, text, entities=None):
    try:
        await bot.send_message(chat_id=chat_id, text=text, entities=entities, disable_web_page_preview=True)
    except TelegramError as e:
        print(f"⚠️ Failed to send: {e}")

# === TELEGRAM BOT LOGIC ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in ALLOWED_USERS:
        return await update.message.reply_text("🚫 Unauthorized user.")
    await update.message.reply_text("👋 Send any message, photo, or video — I'll confirm before posting.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cleanup_pending()
    msg = update.message
    user_id = msg.from_user.id

    if user_id not in ALLOWED_USERS:
        return await msg.reply_text("🚫 You are not authorized to use this bot.")

    text = msg.caption or msg.text
    entities = msg.caption_entities or msg.entities
    photo = msg.photo
    video = msg.video

    # === CONFIRMATION HANDLING ===
    if user_id in pending_messages:
        response = (msg.text or "").strip().lower()
        data = pending_messages[user_id]

        if response in ["yes", "y", "ok", "send"]:
            formatted_text, ents = build_template_entities(data["text"], data.get("entities"))
            for cid in CHANNEL_IDS:
                try:
                    if data["type"] == "text":
                        await safe_send(context.bot, cid, formatted_text, ents)
                    elif data["type"] == "photo":
                        await context.bot.send_photo(chat_id=cid, photo=data["file_id"], caption=formatted_text, caption_entities=ents)
                    elif data["type"] == "video":
                        await context.bot.send_video(chat_id=cid, video=data["file_id"], caption=formatted_text, caption_entities=ents)
                except TelegramError as e:
                    print(f"⚠️ Send failed: {e}")
            await msg.reply_text("✅ Sent to all channels!")
            del pending_messages[user_id]
            return

        elif response in ["no", "n", "cancel"]:
            await msg.reply_text("❌ Cancelled.")
            del pending_messages[user_id]
            return

        else:
            pending_messages[user_id]["text"] = msg.text
            pending_messages[user_id]["entities"] = msg.entities
            preview, ents = build_template_entities(msg.text, msg.entities)
            await msg.reply_text(f"✏️ Updated preview:\n\n{preview}\n\nNow reply 'Yes' to send.", entities=ents)
            return

    # === NEW MESSAGE HANDLING ===
    translated_text = translator.translate(text) if text else ""
    data = {"text": translated_text, "entities": entities, "time": time.time()}

    if photo:
        data["type"] = "photo"
        data["file_id"] = photo[-1].file_id
    elif video:
        data["type"] = "video"
        data["file_id"] = video.file_id
    else:
        data["type"] = "text"

    pending_messages[user_id] = data
    preview, ents = build_template_entities(translated_text, entities)

    if photo:
        await msg.reply_photo(photo=data["file_id"], caption=f"{preview}\n\nSend to channel? (Yes / No)", caption_entities=ents)
    elif video:
        await msg.reply_video(video=data["file_id"], caption=f"{preview}\n\nSend to channel? (Yes / No)", caption_entities=ents)
    else:
        await msg.reply_text(f"{preview}\n\nSend to channel? (Yes / No)", entities=ents)

# === BOT RUNNER ===
async def run_bot():
    app_tg = ApplicationBuilder().token(BOT_TOKEN).build()
    app_tg.add_handler(CommandHandler("start", start))
    app_tg.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO, handle_message))
    print("🚀 Telegram bot is running...")
    await app_tg.initialize()
    await app_tg.start()
    await app_tg.updater.start_polling()
    await asyncio.Event().wait()

# === MAIN ===
if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    threading.Thread(target=ping_self, daemon=True).start()
    asyncio.run(run_bot())
