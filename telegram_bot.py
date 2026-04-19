
import os
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

BOT_TOKEN = os.getenv("BOT_TOKEN")
ALLOWED_USERS = {7173549132, 7050803817}
SELF_URL = os.getenv("SELF_URL", "")

pending_messages = {}
silent_mode = {}

channel_groups = {"vanced": [], "crunchy": []}

footer_enabled = True
footer_title = "Join Backup Channel 👇"
footer_channels = {"vanced": [], "crunchy": []}

app_web = Flask(__name__)

@app_web.route("/")
def home():
    return "Bot Running"

def run_web():
    app_web.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))

def ping():
    while True:
        if SELF_URL:
            try: requests.get(SELF_URL)
            except: pass
        time.sleep(300)

def build_template(text, group=None):
    msg = f"👇👇👇\n\n{text}\n\n"
    if footer_enabled and group and footer_channels.get(group):
        msg += f"{footer_title}\n\n"
        for ch in footer_channels[group]:
            msg += f"👉 {ch}\n"
    return msg.strip()

def preview_buttons(uid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📺 Footer ON" if footer_enabled else "📺 Footer OFF", callback_data="toggle_footer")],
        [InlineKeyboardButton("✏️ Edit Caption", callback_data="edit_caption")],
        [
            InlineKeyboardButton("🎮 Vanced", callback_data="vanced"),
            InlineKeyboardButton("🍿 Crunchy", callback_data="crunchy"),
        ],
        [InlineKeyboardButton("🚀 Both", callback_data="both")]
    ])

def build_post_buttons(btns):
    return InlineKeyboardMarkup([[InlineKeyboardButton(b["name"], url=b["link"])] for b in btns]) if btns else None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id in ALLOWED_USERS:
        await update.message.reply_text("Send post")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in ALLOWED_USERS: return

    text = update.message.text or update.message.caption or ""

    if context.user_data.get("edit_caption"):
        pending_messages[uid]["text"] = text
        context.user_data.pop("edit_caption")
        await update.message.reply_text(build_template(text, "vanced"), reply_markup=preview_buttons(uid))
        return

    msg = update.message

    pending_messages[uid] = {
        "text": text,
        "buttons": [],
        "chat_id": msg.chat_id,
        "message_id": msg.message_id,
        "type": "text",
        "file_id": None
    }

    if msg.photo:
        pending_messages[uid]["type"] = "photo"
        pending_messages[uid]["file_id"] = msg.photo[-1].file_id

    elif msg.video:
        pending_messages[uid]["type"] = "video"
        pending_messages[uid]["file_id"] = msg.video.file_id

    await update.message.reply_text(build_template(text, "vanced"), reply_markup=preview_buttons(uid))

async def send(context, cid, data, group):
    caption = build_template(data["text"], group)
    buttons = build_post_buttons(data["buttons"])

    # ✅ TRY PERFECT METHOD FIRST
    try:
        await context.bot.copy_message(
            chat_id=cid,
            from_chat_id=data["chat_id"],
            message_id=data["message_id"],
            caption=caption,
            reply_markup=buttons
        )
        return
    except:
        pass

    # ✅ FALLBACK
    try:
        if data["type"] == "photo":
            await context.bot.send_photo(cid, data["file_id"], caption=caption, reply_markup=buttons)
        elif data["type"] == "video":
            await context.bot.send_video(cid, data["file_id"], caption=caption, reply_markup=buttons)
        else:
            await context.bot.send_message(cid, caption, reply_markup=buttons)
    except:
        await context.bot.send_message(cid, caption)

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    if q.data == "edit_caption":
        context.user_data["edit_caption"] = True
        await q.message.reply_text("Send new caption")
        return

    if uid not in pending_messages: return
    data = pending_messages[uid]

    if q.data == "vanced":
        targets = channel_groups["vanced"]
        group = "vanced"
    elif q.data == "crunchy":
        targets = channel_groups["crunchy"]
        group = "crunchy"
    else:
        targets = channel_groups["vanced"] + channel_groups["crunchy"]
        group = None

    for cid in targets:
        await send(context, cid, data, group or "vanced")

    pending_messages.pop(uid, None)
    await q.message.delete()

def run():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.ALL, handle_message))
    app.add_handler(CallbackQueryHandler(callback))
    app.run_polling()

if __name__ == "__main__":
    threading.Thread(target=run_web).start()
    threading.Thread(target=ping, daemon=True).start()
    run()

