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

# ===== CONFIG =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
# Ensure your user IDs are correct here
ALLOWED_USERS = {7173549132, 7050803817}
SELF_URL = os.getenv("SELF_URL", "")

pending_messages = {}
silent_mode = {}

channel_groups = {"vanced": [], "crunchy": []}

# ===== FOOTER SYSTEM =====
footer_enabled = True
footer_title = "Join Backup Channel 👇"
footer_channels = {
    "vanced": [],
    "crunchy": []
}

# ===== WEB SERVER =====
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

# ===== TEMPLATE BUILDER =====
def build_template(text, group=None):
    msg = f"👇👇👇\n\n{text}\n\n"

    if footer_enabled and group and footer_channels.get(group):
        msg += f"{footer_title}\n\n"
        for ch in footer_channels[group]:
            msg += f"👉 {ch}\n"

    return msg.strip()

# ===== BUTTONS =====
def preview_buttons(user_id):
    silent = silent_mode.get(user_id, False)

    return InlineKeyboardMarkup([
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

def build_post_buttons(btns):
    if not btns:
        return None
    return InlineKeyboardMarkup([[InlineKeyboardButton(b["name"], url=b["link"])] for b in btns])

# ===== ADMIN PANEL MENUS =====
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
        [
            InlineKeyboardButton("➕ Add Vanced", callback_data="add_footer_v"),
            InlineKeyboardButton("➕ Add Crunchy", callback_data="add_footer_c"),
        ],
        [
            InlineKeyboardButton("➖ Remove Vanced", callback_data="remove_footer_v"),
            InlineKeyboardButton("➖ Remove Crunchy", callback_data="remove_footer_c"),
        ],
        [InlineKeyboardButton("📋 Show Footer", callback_data="show_footer")],
        [InlineKeyboardButton("🔙 Back", callback_data="p_back")]
    ])

# ===== COMMANDS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ALLOWED_USERS: return
    await update.message.reply_text("✅ Send or forward post content (Text, Photo, or Video) to start.")

async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ALLOWED_USERS: return
    await update.message.reply_text("⚙️ Admin Panel", reply_markup=panel_menu())

# ===== MESSAGE HANDLER =====
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global footer_title
    uid = update.effective_user.id
    if uid not in ALLOWED_USERS: return

    msg = update.message
    if not msg: return
    
    # Get text from message or caption (for photos/videos)
    text = msg.text or msg.caption or ""

    # HANDLE EDIT ACTION
    if context.user_data.get("edit_caption"):
        if uid in pending_messages:
            pending_messages[uid]["text"] = text
            context.user_data.pop("edit_caption")
            
            # Send updated preview
            template = build_template(text, "vanced")
            markup = preview_buttons(uid)
            if pending_messages[uid]["type"] == "photo":
                await msg.reply_photo(photo=pending_messages[uid]["file_id"], caption=template, reply_markup=markup)
            elif pending_messages[uid]["type"] == "video":
                await msg.reply_video(video=pending_messages[uid]["file_id"], caption=template, reply_markup=markup)
            else:
                await msg.reply_text(template, reply_markup=markup)
        return

    # HANDLE PANEL SETTINGS
    if context.user_data.get("add_post"):
        group = context.user_data.pop("add_post")
        if text.startswith("-100"):
            if text not in channel_groups[group]:
                channel_groups[group].append(text)
                await msg.reply_text(f"✅ Added to {group}")
            else: await msg.reply_text("⚠️ Already added")
        else: await msg.reply_text("❌ Invalid channel ID")
        return

    if context.user_data.get("set_footer_title"):
        footer_title = text
        context.user_data.pop("set_footer_title")
        await msg.reply_text("✅ Footer title updated")
        return

    if context.user_data.get("add_footer"):
        group = context.user_data.pop("add_footer")
        if text.startswith("@") or text.startswith("-100"):
            if text not in footer_channels[group]:
                footer_channels[group].append(text)
            await msg.reply_text(f"✅ Added to {group} footer")
        else: await msg.reply_text("❌ Use @channel or ID")
        return

    # PROCESS NEW POST (TEXT, PHOTO, OR VIDEO)
    pending_messages[uid] = {
        "text": text,
        "buttons": [],
        "type": "text",
        "file_id": None
    }

    if msg.photo:
        pending_messages[uid]["type"] = "photo"
        pending_messages[uid]["file_id"] = msg.photo[-1].file_id
    elif msg.video:
        pending_messages[uid]["type"] = "video"
        pending_messages[uid]["file_id"] = msg.video.file_id

    # SEND VISUAL PREVIEW
    template = build_template(text, "vanced")
    markup = preview_buttons(uid)
    
    if pending_messages[uid]["type"] == "photo":
        await msg.reply_photo(photo=pending_messages[uid]["file_id"], caption=template, reply_markup=markup)
    elif pending_messages[uid]["type"] == "video":
        await msg.reply_video(video=pending_messages[uid]["file_id"], caption=template, reply_markup=markup)
    else:
        await msg.reply_text(template, reply_markup=markup)

# ===== SEND TO CHANNELS =====
async def send_to_channel(context, cid, data, group):
    cap = build_template(data["text"], group)
    btns = build_post_buttons(data["buttons"])
    try:
        if data["type"] == "photo":
            await context.bot.send_photo(chat_id=cid, photo=data["file_id"], caption=cap, reply_markup=btns)
        elif data["type"] == "video":
            await context.bot.send_video(chat_id=cid, video=data["file_id"], caption=cap, reply_markup=btns)
        else:
            await context.bot.send_message(chat_id=cid, text=cap, reply_markup=btns)
    except Exception as e:
        print(f"Error sending to {cid}: {e}")

# ===== CALLBACK HANDLER =====
async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global footer_enabled
    q = update.callback_query
    uid = q.from_user.id
    await q.answer()

    if q.data == "toggle":
        silent_mode[uid] = not silent_mode.get(uid, False)
        await q.edit_message_reply_markup(reply_markup=preview_buttons(uid)); return

    if q.data == "toggle_footer":
        footer_enabled = not footer_enabled
        await q.edit_message_reply_markup(reply_markup=preview_buttons(uid)); return

    if q.data == "edit_caption":
        context.user_data["edit_caption"] = True
        await q.message.reply_text("Send new caption..."); return

    if q.data == "cancel":
        pending_messages.pop(uid, None)
        await q.message.delete(); return

    # Panel Navigation
    if q.data == "p_post": await q.edit_message_text("📡 Post Channels", reply_markup=panel_post()); return
    if q.data == "p_footer": await q.edit_message_text("📺 Footer Settings", reply_markup=panel_footer()); return
    if q.data == "p_back": await q.edit_message_text("⚙️ Admin Panel", reply_markup=panel_menu()); return
    if q.data == "p_close": await q.message.delete(); return

    if q.data == "add_v": context.user_data["add_post"] = "vanced"; await q.message.reply_text("Send Channel ID (starts with -100)"); return
    if q.data == "add_c": context.user_data["add_post"] = "crunchy"; await q.message.reply_text("Send Channel ID (starts with -100)"); return
    if q.data == "add_footer_v": context.user_data["add_footer"] = "vanced"; await q.message.reply_text("Send @channelname"); return
    if q.data == "add_footer_c": context.user_data["add_footer"] = "crunchy"; await q.message.reply_text("Send @channelname"); return

    if q.data == "show_p":
        v_list = "\n".join(channel_groups["vanced"]) or "None"
        c_list = "\n".join(channel_groups["crunchy"]) or "None"
        await q.message.reply_text(f"📡 **Channels:**\n\nVanced:\n{v_list}\n\nCrunchy:\n{c_list}"); return

    # POSTING ACTIONS
    if uid not in pending_messages:
        await q.message.reply_text("❌ No active post content found."); return
    
    data = pending_messages[uid]
    if q.data == "vanced":
        for cid in channel_groups["vanced"]: await send_to_channel(context, cid, data, "vanced")
        await q.message.reply_text("✅ Posted to Vanced Channels")
    elif q.data == "crunchy":
        for cid in channel_groups["crunchy"]: await send_to_channel(context, cid, data, "crunchy")
        await q.message.reply_text("✅ Posted to Crunchy Channels")
    elif q.data == "both":
        for cid in channel_groups["vanced"]: await send_to_channel(context, cid, data, "vanced")
        for cid in channel_groups["crunchy"]: await send_to_channel(context, cid, data, "crunchy")
        await q.message.reply_text("✅ Posted to All Channels")
    
    pending_messages.pop(uid, None)
    await q.message.delete()

# ===== RUN BOT =====
def run():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("panel", panel))

    # IMPORTANT: Added PHOTO and VIDEO filters so captions and media are processed
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO, handle_message))
    app.add_handler(CallbackQueryHandler(callback))

    print("Bot is active...")
    app.run_polling()

if __name__ == "__main__":
    if BOT_TOKEN:
        threading.Thread(target=run_web, daemon=True).start()
        threading.Thread(target=ping, daemon=True).start()
        run()
    else:
        print("CRITICAL ERROR: BOT_TOKEN not found!")
