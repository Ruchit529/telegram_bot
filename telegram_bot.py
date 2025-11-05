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
MESSAGE_TIMEOUT = 120  # seconds

# === FLASK ===
app_web = Flask(__name__)
@app_web.route('/')
def home():
    return "✅ Telegram bot is running!", 200

def run_web():
    port = int(os.getenv("PORT", 10000))
    app_web.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

def ping_self():
    while True:
        try:
            requests.get(SELF_URL, timeout=5)
        except Exception:
            pass
        time.sleep(300)

def cleanup_pending():
    now = time.time()
    for uid in list(pending_messages.keys()):
        if now - pending_messages[uid]["time"] > MESSAGE_TIMEOUT:
            del pending_messages[uid]

# --- Helpers to build template and shift entities ---
TEMPLATE_PREFIX = "👇👇👇\n\n"
TEMPLATE_SUFFIX = f"\n\n👉 JOIN GROUP"

def build_text_and_entities(orig_text: str, orig_entities):
    """
    Returns (full_text, entities_list) where entities_list refers to positions in full_text.
    If orig_entities is None/empty, returns (full_text, None) so we can use parse_mode as fallback.
    We always append the JOIN_GROUP as a text_link entity.
    """
    if orig_text is None:
        orig_text = ""
    full_text = TEMPLATE_PREFIX + orig_text + TEMPLATE_SUFFIX
    # If there are no original entities, return None for entities (we'll use Markdown fallback)
    if not orig_entities:
        # create a text_link entity for JOIN GROUP
        link_offset = len(full_text) - len("JOIN GROUP")
        link_length = len("JOIN GROUP")
        join_ent = MessageEntity(type="text_link", offset=link_offset, length=link_length, url=GROUP_LINK)
        return full_text, [join_ent]

    # shift original entities by prefix length
    shifted = []
    for e in orig_entities:
        # create a new entity preserving type, url (if text_link), user (if text_mention), language (if pre), etc.
        new_off = e.offset + len(TEMPLATE_PREFIX)
        new_len = e.length
        # build new MessageEntity; include url/user if present
        if e.type == "text_link":
            new_ent = MessageEntity(type="text_link", offset=new_off, length=new_len, url=e.url)
        elif e.type == "text_mention":
            new_ent = MessageEntity(type="text_mention", offset=new_off, length=new_len, user=e.user)
        else:
            # other entity types
            new_ent = MessageEntity(type=e.type, offset=new_off, length=new_len, language=getattr(e, "language", None))
        shifted.append(new_ent)
    # add join link entity
    link_offset = len(full_text) - len("JOIN GROUP")
    link_length = len("JOIN GROUP")
    join_ent = MessageEntity(type="text_link", offset=link_offset, length=link_length, url=GROUP_LINK)
    shifted.append(join_ent)
    return full_text, shifted

# safe plain text send splitting (no entities)
async def safe_send_plain(bot, chat_id, text):
    for i in range(0, len(text), 4000):
        await bot.send_message(chat_id=chat_id, text=text[i:i+4000], parse_mode="Markdown", disable_web_page_preview=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    if uid not in ALLOWED_USERS:
        await update.message.reply_text("🚫 You are not authorized.")
        return
    await update.message.reply_text("👋 Send text/photo/video — edit text if needed, then reply 'Yes' to send.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cleanup_pending()
    msg = update.message
    uid = msg.from_user.id
    if uid not in ALLOWED_USERS:
        await msg.reply_text("🚫 You are not authorized.")
        return

    # original content and entities (handle caption/entities for media)
    orig_text = msg.caption if msg.caption is not None else msg.text
    orig_entities = msg.caption_entities if msg.caption is not None else msg.entities

    photo = msg.photo
    video = msg.video

    # If user already has a pending message: interpret the incoming text as confirm / cancel / edit
    if uid in pending_messages:
        reply = (msg.text or "").strip()
        if reply.lower() in ["yes", "y", "ok", "send"]:
            data = pending_messages[uid]
            # data["text"] is the stored original (not wrapped yet)
            send_text = data["text"]
            send_entities = data.get("entities")
            # Build full template and shifted entities
            full_text, ents = build_text_and_entities(send_text, send_entities)
            for cid in CHANNEL_IDS:
                try:
                    if data["type"] == "text":
                        # if we have proper entities and length < limit, send using entities
                        if ents and len(full_text) <= 4096:
                            await context.bot.send_message(chat_id=cid, text=full_text, entities=ents, disable_web_page_preview=True)
                        else:
                            # fallback to plain (escaped) markdown split
                            await safe_send_plain(context.bot, cid, full_text)
                    elif data["type"] == "photo":
                        if ents and len(full_text) <= 1024:
                            # caption limit 1024 for media
                            await context.bot.send_photo(chat_id=cid, photo=data["file_id"], caption=full_text, caption_entities=ents)
                        else:
                            # send caption as plain text then photo (or photo with no entities)
                            await context.bot.send_photo(chat_id=cid, photo=data["file_id"], caption=full_text if len(full_text) <= 1024 else "")
                            if len(full_text) > 1024:
                                await safe_send_plain(context.bot, cid, full_text)
                    elif data["type"] == "video":
                        if ents and len(full_text) <= 1024:
                            await context.bot.send_video(chat_id=cid, video=data["file_id"], caption=full_text, caption_entities=ents)
                        else:
                            await context.bot.send_video(chat_id=cid, video=data["file_id"], caption=full_text if len(full_text) <= 1024 else "")
                            if len(full_text) > 1024:
                                await safe_send_plain(context.bot, cid, full_text)
                except TelegramError as e:
                    print("Send error:", e)
            await msg.reply_text("✅ Sent to all channels!")
            del pending_messages[uid]
            return

        if reply.lower() in ["no", "n", "cancel"]:
            await msg.reply_text("❌ Cancelled.")
            del pending_messages[uid]
            return

        # treat any other text as edit of the stored message
        new_text = msg.text or ""
        # capture formatting entities from this edit message (they apply to msg.entities)
        new_entities = msg.entities
        pending_messages[uid]["text"] = new_text
        pending_messages[uid]["entities"] = new_entities
        # prepare preview using entities if available
        full_text, ents = build_text_and_entities(new_text, new_entities)
        # send preview - use entities if present
        try:
            if ents and len(full_text) <= 4096:
                await msg.reply_text(full_text, entities=ents, disable_web_page_preview=True)
            else:
                await msg.reply_text(full_text, parse_mode="Markdown", disable_web_page_preview=True)
        except Exception:
            # fallback plain
            await msg.reply_text(full_text, disable_web_page_preview=True)
        await msg.reply_text("✏️ Updated preview. Reply 'Yes' to send.")
        return

    # No pending: this is a new message -> translate and create pending
    translated = translator.translate(orig_text) if orig_text else ""
    # store raw translated text and entities from the user's own message so formatting preserved
    pending_data = {"type": "text", "text": translated, "entities": orig_entities, "time": time.time()}
    if photo:
        file_id = photo[-1].file_id
        pending_data.update({"type": "photo", "file_id": file_id})
    if video:
        file_id = video.file_id
        pending_data.update({"type": "video", "file_id": file_id})

    pending_messages[uid] = pending_data

    # Build preview and send it back to user
    full_text, ents = build_text_and_entities(translated, orig_entities)
    try:
        if pending_data["type"] == "text":
            if ents and len(full_text) <= 4096:
                await msg.reply_text(full_text, entities=ents, disable_web_page_preview=True)
            else:
                await msg.reply_text(full_text, parse_mode="Markdown", disable_web_page_preview=True)
        elif pending_data["type"] == "photo":
            if ents and len(full_text) <= 1024:
                await msg.reply_photo(photo=pending_data["file_id"], caption=full_text, caption_entities=ents)
            else:
                await msg.reply_photo(photo=pending_data["file_id"], caption=full_text, parse_mode="Markdown")
        elif pending_data["type"] == "video":
            if ents and len(full_text) <= 1024:
                await msg.reply_video(video=pending_data["file_id"], caption=full_text, caption_entities=ents)
            else:
                await msg.reply_video(video=pending_data["file_id"], caption=full_text, parse_mode="Markdown")
    except Exception:
        # last-resort fallback
        await msg.reply_text(full_text, disable_web_page_preview=True)

    await msg.reply_text("Send to channel? (Yes / No)")

async def run_bot():
    app_tg = ApplicationBuilder().token(BOT_TOKEN).build()
    app_tg.add_handler(CommandHandler("start", start))
    # handle edited messages as normal messages: the library will populate update.edited_message into update.message
    app_tg.add_handler(MessageHandler(filters.ALL, handle_message))
    print("Bot running...")
    await app_tg.run_polling(close_loop=False)

if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    threading.Thread(target=ping_self, daemon=True).start()
    asyncio.run(run_bot())
