import os
import json
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

# ===== CONFIG =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
ALLOWED_USERS = {7173549132, 7050803817}
SELF_URL = os.getenv("SELF_URL", "")

DATA_FILE = "data.json"
pending_messages = {}

# ===== DATA =====
channel_groups = {"vanced": [], "crunchy": []}

footer_enabled = True

footers = {
    "vanced": {"title": "Join Vanced 👇", "channels": []},
    "crunchy": {"title": "Join Crunchy 👇", "channels": []},
}

# ===== LOAD / SAVE =====
def load_data():
    global channel_groups, footers, footer_enabled
    try:
        with open(DATA_FILE, "r") as f:
            data = json.load(f)
            channel_groups = data.get("groups", channel_groups)
            footers.update(data.get("footers", {}))
            footer_enabled = data.get("footer_enabled", True)
    except:
        save_data()

def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump({
            "groups": channel_groups,
            "footers": footers,
            "footer_enabled": footer_enabled
        }, f, indent=4)

# ===== TEMPLATE =====
def build_template(text, group):
    msg = f"👇👇👇\n\n{text}\n\n"

    if footer_enabled:
        f = footers[group]
        if f["channels"]:
            msg += f"{f['title']}\n\n"
            for ch in f["channels"]:
                msg += f"👉 {ch}\n"

    return msg.strip()

# ===== WEB =====
app_web = Flask(__name__)

@app_web.route("/")
def home():
    return "Bot Running"

def run_web():
    app_web.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))

def ping():
    while True:
        if SELF_URL:
            try:
                requests.get(SELF_URL)
            except:
                pass
        time.sleep(300)

# ===== BUTTONS =====
def preview_buttons():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏ Edit Caption", callback_data="edit")],
        [InlineKeyboardButton(
            "📺 Footer ON" if footer_enabled else "📺 Footer OFF",
            callback_data="toggle_footer"
        )],
        [
            InlineKeyboardButton("🎮 Vanced", callback_data="send_vanced"),
            InlineKeyboardButton("🍿 Crunchy", callback_data="send_crunchy"),
        ],
        [InlineKeyboardButton("🚀 Both", callback_data="send_both")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ])

# ===== START =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id in ALLOWED_USERS:
        await update.message.reply_text("Send post")

# ===== PANEL =====
async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ALLOWED_USERS:
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎮 Vanced Channels", callback_data="panel_post_vanced")],
        [InlineKeyboardButton("🍿 Crunchy Channels", callback_data="panel_post_crunchy")],
        [InlineKeyboardButton("📺 Vanced Footer", callback_data="panel_footer_vanced")],
        [InlineKeyboardButton("🍿 Crunchy Footer", callback_data="panel_footer_crunchy")],
    ])

    await update.message.reply_text("⚙ Control Panel", reply_markup=keyboard)

# ===== MESSAGE =====
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in ALLOWED_USERS:
        return

    msg = update.message
    text = msg.text or msg.caption or ""

    # ===== PANEL INPUT =====
    if context.user_data.get("add_post"):
        group = context.user_data.pop("add_post")
        channel_groups[group].append(text)
        save_data()
        await msg.reply_text("✅ Channel added")
        return

    if context.user_data.get("remove_post"):
        group = context.user_data.pop("remove_post")
        if text in channel_groups[group]:
            channel_groups[group].remove(text)
            save_data()
            await msg.reply_text("✅ Channel removed")
        else:
            await msg.reply_text("❌ Not found")
        return

    if context.user_data.get("add_footer"):
        group = context.user_data.pop("add_footer")
        footers[group]["channels"].append(text)
        save_data()
        await msg.reply_text("✅ Footer channel added")
        return

    if context.user_data.get("remove_footer"):
        group = context.user_data.pop("remove_footer")
        if text in footers[group]["channels"]:
            footers[group]["channels"].remove(text)
            save_data()
            await msg.reply_text("✅ Footer channel removed")
        else:
            await msg.reply_text("❌ Not found")
        return

    if context.user_data.get("edit_title"):
        group = context.user_data.pop("edit_title")
        footers[group]["title"] = text
        save_data()
        await msg.reply_text("✅ Title updated")
        return

    # ===== NEW POST =====
    media = None
    file_id = None

    if msg.photo:
        media = "photo"
        file_id = msg.photo[-1].file_id
    elif msg.video:
        media = "video"
        file_id = msg.video.file_id

    pending_messages[uid] = {
        "text": text,
        "media": media,
        "file_id": file_id
    }

    if media == "photo":
        await msg.reply_photo(photo=file_id, caption=text, reply_markup=preview_buttons())
    elif media == "video":
        await msg.reply_video(video=file_id, caption=text, reply_markup=preview_buttons())
    else:
        await msg.reply_text(text, reply_markup=preview_buttons())

# ===== SEND =====
async def send(context, cid, data, group):
    text = build_template(data["text"], group)

    if data["media"] == "photo":
        await context.bot.send_photo(chat_id=cid, photo=data["file_id"], caption=text)
    elif data["media"] == "video":
        await context.bot.send_video(chat_id=cid, video=data["file_id"], caption=text)
    else:
        await context.bot.send_message(chat_id=cid, text=text)

# ===== CALLBACK =====
async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global footer_enabled

    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    if uid not in ALLOWED_USERS:
        return

    # ===== FOOTER TOGGLE =====
    if q.data == "toggle_footer":
        footer_enabled = not footer_enabled
        save_data()
        await q.edit_message_reply_markup(reply_markup=preview_buttons())
        return

    # ===== PANEL POST =====
    if q.data.startswith("panel_post_"):
        group = q.data.split("_")[2]

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add", callback_data=f"add_post_{group}")],
            [InlineKeyboardButton("➖ Remove", callback_data=f"remove_post_{group}")],
            [InlineKeyboardButton("📋 List", callback_data=f"list_post_{group}")],
        ])

        await q.message.reply_text(f"{group.upper()} Channels", reply_markup=keyboard)
        return

    if q.data.startswith("add_post_"):
        context.user_data["add_post"] = q.data.split("_")[2]
        await q.message.reply_text("Send channel ID")
        return

    if q.data.startswith("remove_post_"):
        context.user_data["remove_post"] = q.data.split("_")[2]
        await q.message.reply_text("Send channel ID to remove")
        return

    if q.data.startswith("list_post_"):
        group = q.data.split("_")[2]
        await q.message.reply_text("\n".join(channel_groups[group]) or "No channels")
        return

    # ===== PANEL FOOTER =====
    if q.data.startswith("panel_footer_"):
        group = q.data.split("_")[2]

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏ Title", callback_data=f"title_{group}")],
            [InlineKeyboardButton("➕ Add", callback_data=f"add_footer_{group}")],
            [InlineKeyboardButton("➖ Remove", callback_data=f"remove_footer_{group}")],
            [InlineKeyboardButton("📋 List", callback_data=f"list_footer_{group}")],
        ])

        await q.message.reply_text(f"{group.upper()} Footer", reply_markup=keyboard)
        return

    if q.data.startswith("title_"):
        context.user_data["edit_title"] = q.data.split("_")[1]
        await q.message.reply_text("Send new title")
        return

    if q.data.startswith("add_footer_"):
        context.user_data["add_footer"] = q.data.split("_")[2]
        await q.message.reply_text("Send channel")
        return

    if q.data.startswith("remove_footer_"):
        context.user_data["remove_footer"] = q.data.split("_")[2]
        await q.message.reply_text("Send channel to remove")
        return

    if q.data.startswith("list_footer_"):
        group = q.data.split("_")[2]
        await q.message.reply_text("\n".join(footers[group]["channels"]) or "No footer channels")
        return

    # ===== SEND =====
    if uid not in pending_messages:
        return

    data = pending_messages[uid]

    if q.data == "cancel":
        pending_messages.pop(uid, None)
        await q.message.delete()
        return

    if q.data == "send_vanced":
        for cid in channel_groups["vanced"]:
            await send(context, cid, data, "vanced")

    elif q.data == "send_crunchy":
        for cid in channel_groups["crunchy"]:
            await send(context, cid, data, "crunchy")

    elif q.data == "send_both":
        for cid in channel_groups["vanced"]:
            await send(context, cid, data, "vanced")
        for cid in channel_groups["crunchy"]:
            await send(context, cid, data, "crunchy")

    pending_messages.pop(uid, None)
    await q.message.delete()

# ===== RUN =====
def run():
    load_data()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("panel", panel))
    app.add_handler(MessageHandler(filters.ALL, handle_message))
    app.add_handler(CallbackQueryHandler(callback))

    app.run_polling()

# ===== MAIN =====
if __name__ == "__main__":
    threading.Thread(target=run_web).start()
    threading.Thread(target=ping, daemon=True).start()
    run()