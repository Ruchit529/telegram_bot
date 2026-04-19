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

channel_groups = {"vanced": [], "crunchy": []}
footer_enabled = True
footer_title = "Join Backup Channel 👇"
footer_channels = []

# ===== LOAD / SAVE =====
def load_data():
    global channel_groups, footer_title, footer_channels, footer_enabled

    try:
        with open(DATA_FILE, "r") as f:
            data = json.load(f)

            channel_groups = data.get("groups", {"vanced": [], "crunchy": []})

            footer = data.get("footer", {})
            footer_enabled = footer.get("enabled", True)
            footer_title = footer.get("title", "Join Backup Channel 👇")
            footer_channels = footer.get("channels", [])

    except FileNotFoundError:
        save_data()

def save_data():
    data = {
        "groups": channel_groups,
        "footer": {
            "enabled": footer_enabled,
            "title": footer_title,
            "channels": footer_channels
        }
    }

    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# ===== WEB =====
app_web = Flask(__name__)

@app_web.route("/")
def home():
    return "Bot Running"

def run_web():
    port = int(os.getenv("PORT", 10000))
    app_web.run(host="0.0.0.0", port=port)

def ping():
    while True:
        if SELF_URL:
            try:
                requests.get(SELF_URL)
            except:
                pass
        time.sleep(300)

# ===== TEMPLATE =====
def build_template(text):
    msg = f"👇👇👇\n\n{text}\n\n"

    if footer_enabled and footer_channels:
        msg += f"{footer_title}\n\n"
        for ch in footer_channels:
            msg += f"👉 {ch}\n"

    return msg.strip()

# ===== BUTTONS =====
def preview_buttons(user_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏ Edit Caption", callback_data="edit_caption")],
        [InlineKeyboardButton("📺 Footer ON" if footer_enabled else "📺 Footer OFF", callback_data="toggle_footer")],
        [
            InlineKeyboardButton("🎮 Vanced", callback_data="vanced"),
            InlineKeyboardButton("🍿 Crunchy", callback_data="crunchy"),
        ],
        [InlineKeyboardButton("🚀 Send to Both", callback_data="both")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ])

# ===== PANEL =====
def panel_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📡 Post Channels", callback_data="p_post")],
        [InlineKeyboardButton("📺 Footer Settings", callback_data="p_footer")],
        [InlineKeyboardButton("❌ Close", callback_data="p_close")]
    ])

def panel_post():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Vanced", callback_data="add_v")],
        [InlineKeyboardButton("➕ Add Crunchy", callback_data="add_c")],
        [
            InlineKeyboardButton("➖ Remove Vanced", callback_data="remove_v"),
            InlineKeyboardButton("➖ Remove Crunchy", callback_data="remove_c"),
        ],
        [InlineKeyboardButton("📋 Show Channels", callback_data="show_p")],
        [InlineKeyboardButton("🔙 Back", callback_data="p_back")]
    ])

def panel_footer():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏ Set Title", callback_data="set_footer_title")],
        [InlineKeyboardButton("➕ Add Channel", callback_data="add_footer")],
        [InlineKeyboardButton("➖ Remove Channel", callback_data="remove_footer")],
        [InlineKeyboardButton("📋 Show Footer", callback_data="show_footer")],
        [InlineKeyboardButton("🔙 Back", callback_data="p_back")]
    ])

# ===== COMMANDS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ALLOWED_USERS:
        return
    await update.message.reply_text("Send or forward post")

async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ALLOWED_USERS:
        return
    await update.message.reply_text("⚙️ Admin Panel", reply_markup=panel_menu())

# ===== MESSAGE =====
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    global footer_title

    uid = update.effective_user.id
    if uid not in ALLOWED_USERS:
        return

    msg = update.message
    text = msg.text or msg.caption or ""

    # ===== ADD CHANNEL =====
    if context.user_data.get("add_post"):
        group = context.user_data.pop("add_post")

        if text.startswith("-100"):
            if text not in channel_groups[group]:
                channel_groups[group].append(text)
                save_data()
            await msg.reply_text(f"✅ Added to {group}")
        else:
            await msg.reply_text("❌ Invalid ID")
        return

    # ===== REMOVE CHANNEL =====
    if context.user_data.get("remove_post"):
        group = context.user_data.pop("remove_post")

        if text in channel_groups[group]:
            channel_groups[group].remove(text)
            save_data()
            await msg.reply_text(f"❌ Removed from {group}")
        else:
            await msg.reply_text("Not found")
        return

    # ===== FOOTER TITLE =====
    if context.user_data.get("set_footer_title"):
        footer_title = text
        save_data()
        context.user_data.pop("set_footer_title")
        await msg.reply_text("✅ Updated")
        return

    # ===== ADD FOOTER =====
    if context.user_data.get("add_footer"):
        if text.startswith("@"):
            if text not in footer_channels:
                footer_channels.append(text)
                save_data()
            await msg.reply_text("✅ Added")
        else:
            await msg.reply_text("❌ Must be @channel")

        context.user_data.pop("add_footer")
        return

    # ===== REMOVE FOOTER =====
    if context.user_data.get("remove_footer"):
        if text in footer_channels:
            footer_channels.remove(text)
            save_data()
            await msg.reply_text("❌ Removed")
        else:
            await msg.reply_text("Not found")

        context.user_data.pop("remove_footer")
        return

    # ===== EDIT CAPTION =====
    if context.user_data.get("edit_caption"):
        if uid in pending_messages:
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

    # ===== NEW POST =====
    media = None
    file_id = None

    if msg.photo:
        media = "photo"
        file_id = msg.photo[-1].file_id
    elif msg.video:
        media = "video"
        file_id = msg.video.file_id

    pending_messages[uid] = {"text": text, "media": media, "file_id": file_id}

    if media == "photo":
        await msg.reply_photo(file_id, caption=build_template(text), reply_markup=preview_buttons(uid), parse_mode=None)
    elif media == "video":
        await msg.reply_video(file_id, caption=build_template(text), reply_markup=preview_buttons(uid), parse_mode=None)
    else:
        await msg.reply_text(build_template(text), reply_markup=preview_buttons(uid), parse_mode=None)

# ===== SEND =====
async def send(context, cid, data):
    if data["media"] == "photo":
        await context.bot.send_photo(cid, data["file_id"], caption=build_template(data["text"]), parse_mode=None)
    elif data["media"] == "video":
        await context.bot.send_video(cid, data["file_id"], caption=build_template(data["text"]), parse_mode=None)
    else:
        await context.bot.send_message(cid, build_template(data["text"]), parse_mode=None)

# ===== CALLBACK =====
async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):

    global footer_enabled

    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    # PANEL NAV
    if q.data == "p_post":
        await q.edit_message_text("📡 Post Channels", reply_markup=panel_post()); return
    if q.data == "p_footer":
        await q.edit_message_text("📺 Footer Settings", reply_markup=panel_footer()); return
    if q.data == "p_back":
        await q.edit_message_text("⚙️ Admin Panel", reply_markup=panel_menu()); return
    if q.data == "p_close":
        await q.message.delete(); return

    # CHANNEL CONTROL
    if q.data == "add_v":
        context.user_data["add_post"] = "vanced"
        await q.message.reply_text("Send channel ID"); return
    if q.data == "add_c":
        context.user_data["add_post"] = "crunchy"
        await q.message.reply_text("Send channel ID"); return
    if q.data == "remove_v":
        context.user_data["remove_post"] = "vanced"
        await q.message.reply_text("Send ID to remove"); return
    if q.data == "remove_c":
        context.user_data["remove_post"] = "crunchy"
        await q.message.reply_text("Send ID to remove"); return
    if q.data == "show_p":
        text = ""
        for g, ids in channel_groups.items():
            text += f"{g}:\n" + ("\n".join(ids) or "none") + "\n\n"
        await q.message.reply_text(text); return

    # FOOTER CONTROL
    if q.data == "set_footer_title":
        context.user_data["set_footer_title"] = True
        await q.message.reply_text("Send new title"); return
    if q.data == "add_footer":
        context.user_data["add_footer"] = True
        await q.message.reply_text("Send @channel"); return
    if q.data == "remove_footer":
        context.user_data["remove_footer"] = True
        await q.message.reply_text("Send channel to remove"); return
    if q.data == "show_footer":
        text = footer_title + "\n\n" + ("\n".join(footer_channels) or "none")
        await q.message.reply_text(text); return

    # NORMAL FLOW
    if q.data == "edit_caption":
        context.user_data["edit_caption"] = True
        await q.message.reply_text("✏ Send new caption"); return

    if q.data == "toggle_footer":
        footer_enabled = not footer_enabled
        save_data()
        await q.edit_message_reply_markup(reply_markup=preview_buttons(uid)); return

    if uid not in pending_messages:
        return

    data = pending_messages[uid]

    if q.data == "cancel":
        pending_messages.pop(uid, None)
        await q.message.delete()
        return

    if q.data == "vanced":
        targets = channel_groups["vanced"]
    elif q.data == "crunchy":
        targets = channel_groups["crunchy"]
    else:
        targets = channel_groups["vanced"] + channel_groups["crunchy"]

    for cid in targets:
        await send(context, cid, data)

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