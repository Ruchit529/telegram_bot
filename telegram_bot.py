import os
import asyncio
import threading
import time
import requests
import re
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
MESSAGE_TIMEOUT = 120

# === FLASK SERVER ===
app_web = Flask(__name__)

@app_web.route('/')
def home():
    return "✅ Telegram bot is running!", 200

def run_web():
    port = int(os.getenv("PORT", 10000))
    app_web.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

# === KEEP ALIVE ===
def ping_self():
    while True:
        try:
            requests.get(SELF_URL, timeout=5)
            print(f"🔁 Pinged {SELF_URL}")
        except Exception as e:
            print(f"⚠️ Ping failed: {e}")
        time.sleep(300)

# === CLEANUP ===
def cleanup_pending():
    now = time.time()
    for uid in list(pending_messages.keys()):
        if now - pending_messages[uid]["time"] > MESSAGE_TIMEOUT:
            del pending_messages[uid]

# === TEMPLATE BUILDER ===
TEMPLATE_PREFIX = "👇👇👇\n\n"
TEMPLATE_SUFFIX = f"\n\n👉 JOIN GROUP"

def build_text_and_entities(orig_text: str, orig_entities):
    if orig_text is None:
        orig_text = ""
    full_text = TEMPLATE_PREFIX + orig_text + TEMPLATE_SUFFIX

    # handle entities shifting
    if not orig_entities:
        link_offset = len(full_text) - len("JOIN GROUP")
        link_entity = MessageEntity("text_link", offset=link_offset, length=len("JOIN GROUP"), url=GROUP_LINK)
        return full_text, [link_entity]

    shifted = []
    for e in orig_entities:
        new_off = e.offset + len(TEMPLATE_PREFIX)
        if e.type == "text_link":
            shifted.append(MessageEntity("text_link", new_off, e.length, url=e.url))
        elif e.type == "text_mention":
            shifted.append(MessageEntity("text_mention", new_off, e.length, user=e.user))
        else:
            shifted.append(MessageEntity(e.type, new_off, e.length))
    link_offset = len(full_text) - len("JOIN GROUP")
    shifted.append(MessageEntity("text_link", link_offset, len("JOIN GROUP"), url=GROUP_LINK))
    return full_text, shifted

# === SAFE SEND ===
async def safe_send_plain(bot, chat_id, text):
    for i in range(0, len(text), 4000):
        await bot.send_message(chat_id=chat_id, text=text[i:i+4000], disable_web_page_preview=True)

# === TELEGRAM LOGIC ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ALLOWED_USERS:
        return await update.message.reply_text("🚫 Unauthorized user.")
    await update.message.reply_text("👋 Send text/photo/video — then 'Yes' to send or edit before.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cleanup_pending()
    msg = update.message
    uid = msg.from_user.id
    if uid not in ALLOWED_USERS:
        return await msg.reply_text("🚫 Unauthorized user.")

    text = msg.caption or msg.text
    entities = msg.caption_entities or msg.entities
    photo = msg.photo
    video = msg.video

    # === Confirmation/Edit ===
    if uid in pending_messages:
        reply = (msg.text or "").strip().lower()
        if reply in ["yes", "y", "ok", "send"]:
            data = pending_messages[uid]
            full_text, ents = build_text_and_entities(data["text"], data.get("entities"))
            for cid in CHANNEL_IDS:
                try:
                    if data["type"] == "text":
                        if ents:
                            await context.bot.send_message(chat_id=cid, text=full_text, entities=ents)
                        else:
                            await safe_send_plain(context.bot, cid, full_text)
                    elif data["type"] == "photo":
                        await context.bot.send_photo(chat_id=cid, photo=data["file_id"], caption=full_text, caption_entities=ents)
                    elif data["type"] == "video":
                        await context.bot.send_video(chat_id=cid, video=data["file_id"], caption=full_text, caption_entities=ents)
                except TelegramError as e:
                    print(f"⚠️ Send failed: {e}")
            await msg.reply_text("✅ Sent to all channels!")
            del pending_messages[uid]
            return

        elif reply in ["no", "n", "cancel"]:
            await msg.reply_text("❌ Cancelled.")
            del pending_messages[uid]
            return

        # treat as edit
        pending_messages[uid]["text"] = msg.text
        pending_messages[uid]["entities"] = msg.entities
        preview, ents = build_text_and_entities(msg.text, msg.entities)
        await msg.reply_text(preview, entities=ents)
        await msg.reply_text("✏️ Preview updated. Reply 'Yes' to send.")
        return

    # === New message ===
    translated = translator.translate(text) if text else ""
    data = {"type": "text", "text": translated, "entities": entities, "time": time.time()}
    if photo:
        data["type"] = "photo"
        data["file_id"] = photo[-1].file_id
    elif video:
        data["type"] = "video"
        data["file_id"] = video.file_id
    pending_messages[uid] = data

    preview, ents = build_text_and_entities(translated, entities)
    if data["type"] == "photo":
        await msg.reply_photo(photo=data["file_id"], caption=preview, caption_entities=ents)
    elif data["type"] == "video":
        await msg.reply_video(video=data["file_id"], caption=preview, caption_entities=ents)
    else:
        await msg.reply_text(preview, entities=ents)
    await msg.reply_text("Send to channel? (Yes / No)")

# === BOT RUNNER ===
async def run_bot():
    app_tg = ApplicationBuilder().token(BOT_TOKEN).build()
    app_tg.add_handler(CommandHandler("start", start))
    app_tg.add_handler(MessageHandler(filters.ALL, handle_message))
    print("🚀 Telegram bot is running...")
    await app_tg.run_polling(close_loop=False)

# === MAIN FIXED (Render Safe) ===
if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    threading.Thread(target=ping_self, daemon=True).start()

    # 🔧 Run bot inside the existing event loop (Render-safe)
    loop = asyncio.get_event_loop()
    loop.create_task(run_bot())
    loop.run_forever()
