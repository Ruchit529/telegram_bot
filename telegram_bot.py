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

DATA_FILE = "/data/data.json"  # Render disk

pending_messages = {}

channel_groups = {"vanced": [], "crunchy": []}

# 🔥 NEW FOOTER SYSTEM
footers = {
    "vanced": {"enabled": True, "title": "Join Vanced 👇", "channels": []},
    "crunchy": {"enabled": True, "title": "Join Crunchy 👇", "channels": []}
}

# ===== LOAD / SAVE =====
def load_data():
    global channel_groups, footers

    try:
        with open(DATA_FILE, "r") as f:
            data = json.load(f)
            channel_groups = data.get("groups", channel_groups)
            footers = data.get("footer", footers)
    except:
        save_data()

def save_data():
    data = {
        "groups": channel_groups,
        "footer": footers
    }
    os.makedirs("/data", exist_ok=True)
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

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

# ===== TEMPLATE =====
def build_template(text, group=None):
    msg = f"👇👇👇\n\n{text}\n\n"

    if group and group in footers:
        f = footers[group]
        if f["enabled"] and f["channels"]:
            msg += f"{f['title']}\n\n"
            for ch in f["channels"]:
                msg += f"👉 {ch}\n"

    return msg.strip()

# ===== BUTTONS =====
def preview_buttons(uid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏ Edit Caption", callback_data="edit_caption")],
        [InlineKeyboardButton("🎮 Vanced", callback_data="vanced"),
         InlineKeyboardButton("🍿 Crunchy", callback_data="crunchy")],
        [InlineKeyboardButton("🚀 Send Both", callback_data="both")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ])

# ===== PANEL =====
def panel_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📡 Channels", callback_data="p_post")],
        [InlineKeyboardButton("📺 Footer", callback_data="p_footer")],
        [InlineKeyboardButton("❌ Close", callback_data="p_close")]
    ])

def panel_footer_select():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎮 Vanced", callback_data="p_footer_v")],
        [InlineKeyboardButton("🍿 Crunchy", callback_data="p_footer_c")],
        [InlineKeyboardButton("🔙 Back", callback_data="p_back")]
    ])

def panel_footer():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏ Set Title", callback_data="set_footer_title")],
        [InlineKeyboardButton("➕ Add Channel", callback_data="add_footer")],
        [InlineKeyboardButton("➖ Remove Channel", callback_data="remove_footer")],
        [InlineKeyboardButton("📋 Show Footer", callback_data="show_footer")],
        [InlineKeyboardButton("🔙 Back", callback_data="p_footer")]
    ])

# ===== COMMAND =====
async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ALLOWED_USERS:
        return
    await update.message.reply_text("⚙️ Panel", reply_markup=panel_menu())

# ===== MESSAGE =====
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in ALLOWED_USERS:
        return

    msg = update.message
    text = msg.text or msg.caption or ""

    # FOOTER EDIT
    group = context.user_data.get("footer_group")

    if context.user_data.get("set_footer_title"):
        footers[group]["title"] = text
        save_data()
        context.user_data.pop("set_footer_title")
        await msg.reply_text("✅ Updated")
        return

    if context.user_data.get("add_footer"):
        footers[group]["channels"].append(text)
        save_data()
        context.user_data.pop("add_footer")
        await msg.reply_text("✅ Added")
        return

    if context.user_data.get("remove_footer"):
        if text in footers[group]["channels"]:
            footers[group]["channels"].remove(text)
            save_data()
        context.user_data.pop("remove_footer")
        await msg.reply_text("❌ Removed")
        return

    # EDIT CAPTION
    if context.user_data.get("edit_caption"):
        pending_messages[uid]["text"] = text
        data = pending_messages[uid]

        if data["media"] == "photo":
            await msg.reply_photo(data["file_id"], caption=build_template(text), reply_markup=preview_buttons(uid), parse_mode=None)
        elif data["media"] == "video":
            await msg.reply_video(data["file_id"], caption=build_template(text), reply_markup=preview_buttons(uid), parse_mode=None)
        else:
            await msg.reply_text(build_template(text), reply_markup=preview_buttons(uid), parse_mode=None)

        context.user_data.pop("edit_caption")
        return

    # NEW POST
    media, file_id = None, None
    if msg.photo:
        media, file_id = "photo", msg.photo[-1].file_id
    elif msg.video:
        media, file_id = "video", msg.video.file_id

    pending_messages[uid] = {"text": text, "media": media, "file_id": file_id}

    if media == "photo":
        await msg.reply_photo(file_id, caption=build_template(text), reply_markup=preview_buttons(uid), parse_mode=None)
    elif media == "video":
        await msg.reply_video(file_id, caption=build_template(text), reply_markup=preview_buttons(uid), parse_mode=None)
    else:
        await msg.reply_text(build_template(text), reply_markup=preview_buttons(uid), parse_mode=None)

# ===== SEND =====
async def send(context, cid, data, group):
    caption = build_template(data["text"], group)

    if data["media"] == "photo":
        await context.bot.send_photo(cid, data["file_id"], caption=caption, parse_mode=None)
    elif data["media"] == "video":
        await context.bot.send_video(cid, data["file_id"], caption=caption, parse_mode=None)
    else:
        await context.bot.send_message(cid, caption, parse_mode=None)

# ===== CALLBACK =====
async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    # PANEL NAV
    if q.data == "p_footer":
        await q.edit_message_text("Select Footer", reply_markup=panel_footer_select()); return
    if q.data == "p_footer_v":
        context.user_data["footer_group"] = "vanced"
        await q.edit_message_text("🎮 Vanced Footer", reply_markup=panel_footer()); return
    if q.data == "p_footer_c":
        context.user_data["footer_group"] = "crunchy"
        await q.edit_message_text("🍿 Crunchy Footer", reply_markup=panel_footer()); return
    if q.data == "p_back":
        await q.edit_message_text("⚙️ Panel", reply_markup=panel_menu()); return

    if q.data == "set_footer_title":
        context.user_data["set_footer_title"] = True
        await q.message.reply_text("Send title"); return
    if q.data == "add_footer":
        context.user_data["add_footer"] = True
        await q.message.reply_text("Send @channel"); return
    if q.data == "remove_footer":
        context.user_data["remove_footer"] = True
        await q.message.reply_text("Send channel"); return
    if q.data == "show_footer":
        g = context.user_data.get("footer_group")
        f = footers[g]
        text = f["title"] + "\n\n" + "\n".join(f["channels"])
        await q.message.reply_text(text); return

    # SEND
    if uid not in pending_messages:
        return

    data = pending_messages[uid]

    if q.data == "vanced":
        for cid in channel_groups["vanced"]:
            await send(context, cid, data, "vanced")

    elif q.data == "crunchy":
        for cid in channel_groups["crunchy"]:
            await send(context, cid, data, "crunchy")

    elif q.data == "both":
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

    app.add_handler(CommandHandler("panel", panel))
    app.add_handler(MessageHandler(filters.ALL, handle_message))
    app.add_handler(CallbackQueryHandler(callback))

    app.run_polling()

# ===== MAIN =====
if __name__ == "__main__":
    threading.Thread(target=run_web).start()
    threading.Thread(target=ping, daemon=True).start()
    run()