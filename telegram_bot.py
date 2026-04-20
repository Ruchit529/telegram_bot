import os
import threading
import time
import requests
import logging
import json
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

# Setup logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ===== CONFIG =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
ALLOWED_USERS = {7173549132, 7050803817}
SELF_URL = os.getenv("SELF_URL", "")
DATA_FILE = "bot_config.json"

pending_messages = {}
silent_mode = {}

# Settings
channel_groups = {"vanced": [], "crunchy": []}
footer_enabled = True
footer_title = "Join Backup Channel 👇"
footer_channels = {"vanced": [], "crunchy": []}

def save_data():
    try:
        with open(DATA_FILE, "w") as f:
            json.dump({
                "channel_groups": channel_groups,
                "footer_enabled": footer_enabled,
                "footer_title": footer_title,
                "footer_channels": footer_channels
            }, f)
    except Exception as e: logger.error(f"Save error: {e}")

def load_data():
    global channel_groups, footer_enabled, footer_title, footer_channels
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                data = json.load(f)
                channel_groups = data.get("channel_groups", channel_groups)
                footer_enabled = data.get("footer_enabled", footer_enabled)
                footer_title = data.get("footer_title", footer_title)
                footer_channels = data.get("footer_channels", footer_channels)
        except Exception as e: logger.error(f"Load error: {e}")

load_data()

# ===== WEB & PING =====
app_web = Flask(__name__)
@app_web.route("/")
def home(): return "Bot Online"

def run_web():
    port = int(os.getenv("PORT", 10000))
    app_web.run(host="0.0.0.0", port=port)

def ping():
    while True:
        if SELF_URL:
            try: requests.get(SELF_URL, timeout=10)
            except: pass
        time.sleep(300)

# ===== UI BUILDERS =====
def build_template(text, group=None):
    msg = f"👇👇👇\n\n{text}\n\n"
    if footer_enabled and group and footer_channels.get(group):
        msg += f"{footer_title}\n\n"
        for ch in footer_channels[group]: msg += f"👉 {ch}\n"
    return msg.strip()

def preview_buttons(user_id, custom_btns=None):
    keyboard = []
    if custom_btns:
        for b in custom_btns: keyboard.append([InlineKeyboardButton(b["name"], url=b["link"])])
    
    silent = silent_mode.get(user_id, False)
    keyboard.extend([
        [InlineKeyboardButton("🔕 Silent ON" if silent else "🔔 Silent OFF", callback_data="toggle")],
        [InlineKeyboardButton("📺 Footer ON" if footer_enabled else "📺 Footer OFF", callback_data="toggle_footer")],
        [InlineKeyboardButton("➕ Add Button", callback_data="add_btn")],
        [InlineKeyboardButton("✏️ Edit Caption", callback_data="edit_caption")],
        [InlineKeyboardButton("🎮 Vanced Games", callback_data="vanced"), InlineKeyboardButton("🍿 Crunchyroll Anime", callback_data="crunchy")],
        [InlineKeyboardButton("🚀 Send to Both", callback_data="both")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ])
    return InlineKeyboardMarkup(keyboard)

# ===== ADMIN PANELS =====
def panel_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📡 Post Channels", callback_data="p_post")],
        [InlineKeyboardButton("📺 Footer Settings", callback_data="p_footer")],
        [InlineKeyboardButton("❌ Close", callback_data="p_close")]
    ])

def panel_post():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Vanced", callback_data="add_v"), InlineKeyboardButton("➕ Add Crunchy", callback_data="add_c")],
        [InlineKeyboardButton("➖ Remove Vanced", callback_data="remove_v"), InlineKeyboardButton("➖ Remove Crunchy", callback_data="remove_c")],
        [InlineKeyboardButton("📋 Show Channels", callback_data="show_p")],
        [InlineKeyboardButton("🔙 Back", callback_data="p_back")]
    ])

def panel_footer():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏ Set Title", callback_data="set_footer_title")],
        [InlineKeyboardButton("➕ Add Vanced", callback_data="add_footer_v"), InlineKeyboardButton("➕ Add Crunchy", callback_data="add_footer_c")],
        [InlineKeyboardButton("➖ Remove Vanced", callback_data="remove_footer_v"), InlineKeyboardButton("➖ Remove Crunchy", callback_data="remove_footer_c")],
        [InlineKeyboardButton("📋 Show Footer", callback_data="show_footer")],
        [InlineKeyboardButton("🔙 Back", callback_data="p_back")]
    ])

# ===== MESSAGE HANDLER =====
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in ALLOWED_USERS: return
    msg = update.message
    text = msg.text or msg.caption or ""

    # HANDLE ALL SETTINGS MODES
    if context.user_data.get("set_footer_title"):
        global footer_title
        footer_title = text
        context.user_data.pop("set_footer_title")
        save_data(); await msg.reply_text("✅ Footer title updated!")
        return

    if context.user_data.get("add_footer"):
        group = context.user_data.pop("add_footer")
        if text.startswith("@") or text.startswith("-100"):
            footer_channels[group].append(text); save_data(); await msg.reply_text(f"✅ Added to {group} footer.")
        else: await msg.reply_text("❌ Invalid username/ID")
        return

    if context.user_data.get("remove_footer"):
        group = context.user_data.pop("remove_footer")
        if text in footer_channels[group]:
            footer_channels[group].remove(text); save_data(); await msg.reply_text("✅ Removed")
        else: await msg.reply_text("❌ Not found")
        return

    if context.user_data.get("add_post"):
        group = context.user_data.pop("add_post")
        if text.startswith("-100"): channel_groups[group].append(text); save_data(); await msg.reply_text("✅ Added")
        else: await msg.reply_text("❌ Invalid ID")
        return

    if context.user_data.get("adding_btn_name"):
        context.user_data["temp_btn_name"] = text
        context.user_data.pop("adding_btn_name")
        context.user_data["adding_btn_link"] = True
        await msg.reply_text(f"🔗 Send the **Link** for '{text}':")
        return

    if context.user_data.get("adding_btn_link"):
        name = context.user_data.pop("temp_btn_name")
        context.user_data.pop("adding_btn_link")
        if uid in pending_messages:
            pending_messages[uid]["buttons"].append({"name": name, "link": text})
            await msg.reply_text(f"✅ Button '{name}' added!")
        return

    # NEW POST START
    pending_messages[uid] = {"text": text, "buttons": [], "type": "text", "file_id": None}
    if msg.photo: 
        pending_messages[uid]["type"] = "photo"
        pending_messages[uid]["file_id"] = msg.photo[-1].file_id
    elif msg.video:
        pending_messages[uid]["type"] = "video"
        pending_messages[uid]["file_id"] = msg.video.file_id

    kb = preview_buttons(uid, [])
    await msg.reply_text("📸 **New Post Received!**", reply_markup=kb)

# ===== CALLBACK HANDLER =====
async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global footer_enabled
    q = update.callback_query
    uid = q.from_user.id
    await q.answer()

    # --- 1. SETTINGS & NAVIGATION (Do not require pending post) ---
    if q.data == "p_post": await q.edit_message_text("📡 Post Channels", reply_markup=panel_post()); return
    if q.data == "p_footer": await q.edit_message_text("📺 Footer Settings", reply_markup=panel_footer()); return
    if q.data == "p_back": await q.edit_message_text("⚙️ Admin Panel", reply_markup=panel_menu()); return
    if q.data == "p_close": await q.message.delete(); return

    if q.data == "set_footer_title":
        context.user_data["set_footer_title"] = True
        await q.message.reply_text("✏️ Send the new Footer Title:"); return

    if q.data == "show_footer":
        v = "\n".join(footer_channels["vanced"]) or "None"
        c = "\n".join(footer_channels["crunchy"]) or "None"
        await q.message.reply_text(f"📺 **Footer Settings**\n\nTitle: {footer_title}\n\nVanced Footer:\n{v}\n\nCrunchy Footer:\n{c}"); return

    if q.data == "add_footer_v": context.user_data["add_footer"] = "vanced"; await q.message.reply_text("Send @channel for Vanced Footer:"); return
    if q.data == "add_footer_c": context.user_data["add_footer"] = "crunchy"; await q.message.reply_text("Send @channel for Crunchy Footer:"); return
    if q.data == "remove_footer_v": context.user_data["remove_footer"] = "vanced"; await q.message.reply_text("Send channel name to remove from Vanced:"); return
    if q.data == "remove_footer_c": context.user_data["remove_footer"] = "crunchy"; await q.message.reply_text("Send channel name to remove from Crunchy:"); return

    if q.data == "add_btn":
        context.user_data["adding_btn_name"] = True
        await q.message.reply_text("✏️ Send Button Name:"); return

    if q.data == "toggle_footer":
        footer_enabled = not footer_enabled; save_data()
        await q.edit_message_reply_markup(reply_markup=preview_buttons(uid, pending_messages.get(uid, {}).get("buttons", []))); return

    # --- 2. POSTING (Require pending post) ---
    if q.data in ["vanced", "crunchy", "both"]:
        if uid not in pending_messages:
            await q.message.reply_text("❌ No active post found. Send a new image/video first."); return
        
        data = pending_messages[uid]
        if q.data == "vanced":
            for cid in channel_groups["vanced"]: await send_post(context, cid, data, "vanced")
        elif q.data == "crunchy":
            for cid in channel_groups["crunchy"]: await send_post(context, cid, data, "crunchy")
        elif q.data == "both":
            for cid in channel_groups["vanced"]: await send_post(context, cid, data, "vanced")
            for cid in channel_groups["crunchy"]: await send_post(context, cid, data, "crunchy")
        
        await q.message.reply_text("✅ Success!"); await q.message.delete(); pending_messages.pop(uid)

async def send_post(context, cid, data, group):
    cap = build_template(data["text"], group)
    btns = build_post_buttons(data["buttons"])
    try:
        if data["type"] == "photo": await context.bot.send_photo(cid, photo=data["file_id"], caption=cap, reply_markup=btns)
        elif data["type"] == "video": await context.bot.send_video(cid, video=data["file_id"], caption=cap, reply_markup=btns)
        else: await context.bot.send_message(cid, text=cap, reply_markup=btns)
    except Exception as e: logger.error(f"Error: {e}")

def run():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("panel", lambda u, c: u.message.reply_text("Admin Panel", reply_markup=panel_menu())))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO, handle_message))
    app.add_handler(CallbackQueryHandler(callback))
    app.run_polling()

if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    threading.Thread(target=ping, daemon=True).start()
    run()
