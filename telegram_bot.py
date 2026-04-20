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
    """Combines custom post buttons with admin control buttons."""
    silent = silent_mode.get(user_id, False)
    keyboard = []
    
    # 1. Add custom URL buttons to the top of the keyboard
    if custom_btns:
        for b in custom_btns:
            keyboard.append([InlineKeyboardButton(b["name"], url=b["link"])])
            
    # 2. Add admin control panel
    keyboard.extend([
        [InlineKeyboardButton("🔕 Silent ON" if silent else "🔔 Silent OFF", callback_data="toggle")],
        [InlineKeyboardButton("📺 Footer ON" if footer_enabled else "📺 Footer OFF", callback_data="toggle_footer")],
        [InlineKeyboardButton("➕ Add Button", callback_data="add_btn")],
        [InlineKeyboardButton("✏️ Edit Caption", callback_data="edit_caption")],
        [
            InlineKeyboardButton("🎮 Vanced Games", callback_data="vanced"),
            InlineKeyboardButton("🍿 Crunchyroll Anime", callback_data="crunchy"),
        ],
        [InlineKeyboardButton("🚀 Send to Both", callback_data="both")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ])
    return InlineKeyboardMarkup(keyboard)

def build_post_buttons(btns):
    if not btns: return None
    return InlineKeyboardMarkup([[InlineKeyboardButton(b["name"], url=b["link"])] for b in btns])

# ===== ADMIN PANELS =====
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
        [InlineKeyboardButton("➖ Remove Vanced", callback_data="remove_v"), InlineKeyboardButton("➖ Remove Crunchy", callback_data="remove_c")],
        [InlineKeyboardButton("🔙 Back", callback_data="p_back")]
    ])

# ===== HANDLERS =====
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in ALLOWED_USERS: return
    msg = update.message
    text = msg.text or msg.caption or ""

    # 1. ADD BUTTON NAME
    if context.user_data.get("adding_btn_name"):
        context.user_data["temp_btn_name"] = text
        context.user_data.pop("adding_btn_name")
        context.user_data["adding_btn_link"] = True
        await msg.reply_text(f"🔗 Great! Now send the **Link** (URL) for '{text}':")
        return

    # 2. ADD BUTTON LINK
    if context.user_data.get("adding_btn_link"):
        if not (text.startswith("http") or text.startswith("t.me")):
            await msg.reply_text("❌ Invalid Link! Send a valid URL (starting with http or t.me):")
            return
        
        name = context.user_data.pop("temp_btn_name")
        context.user_data.pop("adding_btn_link")
        
        if uid in pending_messages:
            pending_messages[uid]["buttons"].append({"name": name, "link": text})
            # Resend Preview with new button
            data = pending_messages[uid]
            kb = preview_buttons(uid, data["buttons"])
            temp = build_template(data["text"], "vanced")
            if data["type"] == "photo": await msg.reply_photo(data["file_id"], caption=temp, reply_markup=kb)
            elif data["type"] == "video": await msg.reply_video(data["file_id"], caption=temp, reply_markup=kb)
            else: await msg.reply_text(temp, reply_markup=kb)
        return

    # 3. SETTINGS MODES
    if context.user_data.get("add_post"):
        group = context.user_data.pop("add_post")
        if text.startswith("-100"): channel_groups[group].append(text); save_data(); await msg.reply_text("✅ Added")
        else: await msg.reply_text("❌ Invalid ID")
        return

    # 4. NEW POST
    pending_messages[uid] = {"text": text, "buttons": [], "type": "text", "file_id": None}
    if msg.photo:
        pending_messages[uid]["type"] = "photo"
        pending_messages[uid]["file_id"] = msg.photo[-1].file_id
    elif msg.video:
        pending_messages[uid]["type"] = "video"
        pending_messages[uid]["file_id"] = msg.video.file_id

    await msg.reply_text("📸 Preview Generated:", reply_markup=preview_buttons(uid, []))
    # Send actual preview content
    data = pending_messages[uid]
    kb = preview_buttons(uid, [])
    temp = build_template(text, "vanced")
    if data["type"] == "photo": await msg.reply_photo(data["file_id"], caption=temp, reply_markup=kb)
    elif data["type"] == "video": await msg.reply_video(data["file_id"], caption=temp, reply_markup=kb)
    else: await msg.reply_text(temp, reply_markup=kb)

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global footer_enabled
    q = update.callback_query
    uid = q.from_user.id
    await q.answer()

    if q.data == "add_btn":
        context.user_data["adding_btn_name"] = True
        await q.message.reply_text("✏️ Send the **Name** for your button:")
        return

    if q.data == "toggle_footer":
        footer_enabled = not footer_enabled
        save_data()
        await q.edit_message_reply_markup(reply_markup=preview_buttons(uid, pending_messages.get(uid, {}).get("buttons", [])))
        return

    if q.data == "cancel":
        pending_messages.pop(uid, None)
        await q.message.delete(); return

    # Posting logic
    if uid not in pending_messages: return
    data = pending_messages[uid]

    if q.data == "vanced":
        for cid in channel_groups["vanced"]: await send_to_channel(context, cid, data, "vanced")
        await q.message.reply_text("✅ Posted!"); await q.message.delete()
    elif q.data == "both":
        for cid in channel_groups["vanced"]: await send_to_channel(context, cid, data, "vanced")
        for cid in channel_groups["crunchy"]: await send_to_channel(context, cid, data, "crunchy")
        await q.message.reply_text("✅ Posted Both!"); await q.message.delete()

async def send_to_channel(context, cid, data, group):
    cap = build_template(data["text"], group)
    btns = build_post_buttons(data["buttons"])
    try:
        if data["type"] == "photo": await context.bot.send_photo(cid, photo=data["file_id"], caption=cap, reply_markup=btns)
        elif data["type"] == "video": await context.bot.send_video(cid, video=data["file_id"], caption=cap, reply_markup=btns)
        else: await context.bot.send_message(cid, text=cap, reply_markup=btns)
    except Exception as e: logger.error(f"Error: {e}")

def run():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", lambda u, c: u.message.reply_text("Send media to start post.")))
    app.add_handler(CommandHandler("panel", lambda u, c: u.message.reply_text("Admin Panel", reply_markup=panel_menu())))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO, handle_message))
    app.add_handler(CallbackQueryHandler(callback))
    app.run_polling()

if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    threading.Thread(target=ping, daemon=True).start()
    run()
