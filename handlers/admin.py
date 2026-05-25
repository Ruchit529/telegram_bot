import time
import aiosqlite
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters

from config import ADMIN_IDS, logger
from database import db
from services.fsm import fsm, States
from handlers.error_handler import safe_handler, safe_callback, safe_edit_message_text, safe_send_message, safe_delete_message

def is_admin(user_id: int) -> bool:
    """Checks if a Telegram User ID is in the configured ADMIN_IDS list."""
    return user_id in ADMIN_IDS

def admin_only(func):
    """Decorator to restrict commands/callbacks to administrators only."""
    import functools
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id if update.effective_user else None
        if not user_id or not is_admin(user_id):
            logger.warning(f"Unauthorized access attempt by user {user_id}")
            if update.message:
                await update.message.reply_text("⛔️ <b>Access Denied:</b> This bot is restricted to authorized administrators only.", parse_mode="HTML")
            elif update.callback_query:
                await update.callback_query.answer("Access Denied!", show_alert=True)
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

@safe_handler
@admin_only
async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command handler for /admin. Renders the premium administrative control panel."""
    # Reset FSM state
    user_id = update.effective_user.id
    await fsm.clear_state(user_id)
    
    text, keyboard = _build_main_menu()
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)

@safe_callback
@admin_only
async def admin_callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Safe callback query router directing all admin-related button interactions."""
    query = update.callback_query
    data = query.data
    user_id = update.effective_user.id
    bot = context.bot

    # Main Menu
    if data == "admin:panel":
        await fsm.clear_state(user_id)
        text, keyboard = _build_main_menu()
        await safe_edit_message_text(bot, user_id, query.message.message_id, text, parse_mode="HTML", reply_markup=keyboard)

    # Channels Submenu
    elif data == "admin:channels":
        await fsm.clear_state(user_id)
        text, keyboard = await _build_channels_menu()
        await safe_edit_message_text(bot, user_id, query.message.message_id, text, parse_mode="HTML", reply_markup=keyboard)

    # Trigger Awaiting Channel ID FSM States
    elif data == "admin:add_v" or data == "admin:add_c":
        category = "vanced" if "add_v" in data else "crunchy"
        await fsm.set_state(user_id, "AWAITING_ADD_CHANNEL", {"category": category, "admin_msg_id": query.message.message_id})
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back to Channels", callback_data="admin:channels")]])
        await safe_edit_message_text(
            bot, user_id, query.message.message_id,
            f"➕ <b>Add {category.capitalize()} Posting Channel</b>\n\n"
            "Please send the <b>numerical Telegram Channel ID</b> (usually starts with <code>-100</code>).\n\n"
            "<i>💡 Alternatively, forward ANY message from the target channel directly to this chat and I will extract the ID automatically.</i>",
            parse_mode="HTML",
            reply_markup=keyboard
        )

    elif data == "admin:remove_v" or data == "admin:remove_c":
        category = "vanced" if "remove_v" in data else "crunchy"
        await fsm.set_state(user_id, "AWAITING_REMOVE_CHANNEL", {"category": category, "admin_msg_id": query.message.message_id})
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back to Channels", callback_data="admin:channels")]])
        await safe_edit_message_text(
            bot, user_id, query.message.message_id,
            f"➖ <b>Remove {category.capitalize()} Posting Channel</b>\n\n"
            "Please send the <b>numerical Telegram Channel ID</b> of the channel you want to remove.",
            parse_mode="HTML",
            reply_markup=keyboard
        )

    elif data == "admin:show_p":
        v_chans = await db.list_channels_by_category("vanced")
        c_chans = await db.list_channels_by_category("crunchy")
        v_list = "\n".join([f"• {c['title']} (<code>{c['channel_id']}</code>)" for c in v_chans]) or "None"
        c_list = "\n".join([f"• {c['title']} (<code>{c['channel_id']}</code>)" for c in c_chans]) or "None"
        await query.answer()
        await safe_send_message(
            bot, user_id, 
            f"📡 <b>Active Channels List</b>\n\n<b>Vanced:</b>\n{v_list}\n\n<b>Crunchy:</b>\n{c_list}", 
            parse_mode="HTML"
        )

    # Footers Submenu
    elif data == "admin:footers":
        await fsm.clear_state(user_id)
        text, keyboard = await _build_footers_menu()
        await safe_edit_message_text(bot, user_id, query.message.message_id, text, parse_mode="HTML", reply_markup=keyboard)

    # Trigger Awaiting Footer Title FSM state
    elif data == "admin:set_footer_title":
        await fsm.set_state(user_id, "AWAITING_SET_FOOTER_TITLE", {"admin_msg_id": query.message.message_id})
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back to Footers", callback_data="admin:footers")]])
        await safe_edit_message_text(
            bot, user_id, query.message.message_id,
            "✏️ <b>Set Footer Title</b>\n\n"
            "Please enter the new global footer title text below.",
            parse_mode="HTML",
            reply_markup=keyboard
        )

    # Trigger Awaiting Footer Channel ID FSM States
    elif data == "admin:add_footer_v" or data == "admin:add_footer_c":
        category = "vanced" if "add_footer_v" in data else "crunchy"
        await fsm.set_state(user_id, "AWAITING_ADD_FOOTER_CHANNEL", {"category": category, "admin_msg_id": query.message.message_id})
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back to Footers", callback_data="admin:footers")]])
        await safe_edit_message_text(
            bot, user_id, query.message.message_id,
            f"➕ <b>Add {category.capitalize()} Footer Channel Link</b>\n\n"
            "Please enter the channel link (e.g. <code>@channelname</code> or its ID).",
            parse_mode="HTML",
            reply_markup=keyboard
        )

    elif data == "admin:remove_footer_v" or data == "admin:remove_footer_c":
        category = "vanced" if "remove_footer_v" in data else "crunchy"
        await fsm.set_state(user_id, "AWAITING_REMOVE_FOOTER_CHANNEL", {"category": category, "admin_msg_id": query.message.message_id})
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back to Footers", callback_data="admin:footers")]])
        await safe_edit_message_text(
            bot, user_id, query.message.message_id,
            f"➖ <b>Remove {category.capitalize()} Footer Channel Link</b>\n\n"
            "Please enter the link (e.g. <code>@channelname</code>) of the channel you want to remove.",
            parse_mode="HTML",
            reply_markup=keyboard
        )

    elif data == "admin:show_footer":
        v_footers = await db.list_footer_channels_by_category("vanced")
        c_footers = await db.list_footer_channels_by_category("crunchy")
        v_list = "\n".join([f"👉 {f['channel_id']}" for f in v_footers]) or "None"
        c_list = "\n".join([f"👉 {f['channel_id']}" for f in c_footers]) or "None"
        await query.answer()
        await safe_send_message(
            bot, user_id, 
            f"📺 <b>Active Footer Channels List</b>\n\n<b>Vanced:</b>\n{v_list}\n\n<b>Crunchy:</b>\n{c_list}", 
            parse_mode="HTML"
        )

    # Posting Queue Submenu
    elif data == "admin:queue":
        await fsm.clear_state(user_id)
        text, keyboard = await _build_queue_menu()
        await safe_edit_message_text(bot, user_id, query.message.message_id, text, parse_mode="HTML", reply_markup=keyboard)

    # Cancel Queue Item Action
    elif data.startswith("admin:cancel_q:"):
        queue_id = int(data.split(":")[-1])
        await db.cancel_queue_item(queue_id)
        text, keyboard = await _build_queue_menu()
        await safe_edit_message_text(bot, user_id, query.message.message_id, text, parse_mode="HTML", reply_markup=keyboard)
        await query.answer("Queue item cancelled.")

    # Diagnostics Submenu
    elif data == "admin:diagnostics":
        await fsm.clear_state(user_id)
        text, keyboard = await _build_diagnostics_menu()
        await safe_edit_message_text(bot, user_id, query.message.message_id, text, parse_mode="HTML", reply_markup=keyboard)

    # Close Menu Safely
    elif data == "admin:close":
        await fsm.clear_state(user_id)
        await safe_delete_message(bot, user_id, query.message.message_id)

# --- FSM Admin Input Receivers ---

@safe_handler
@admin_only
async def handle_admin_text_inputs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processes textual inputs from admins when FSM is active for configuration steps."""
    user_id = update.effective_user.id
    state, data = await fsm.get_state(user_id)
    bot = context.bot

    if not state or state == States.NONE:
        return

    # Delete user's input message to keep workspace clean
    await safe_delete_message(bot, user_id, update.message.message_id)

    admin_msg_id = data.get("admin_msg_id")
    text_input = update.message.text.strip()

    if state == "AWAITING_ADD_CHANNEL":
        category = data.get("category")
        try:
            channel_id = int(text_input)
            chat = await bot.get_chat(channel_id)
            await db.add_channel(channel_id, chat.title, category)
            await fsm.clear_state(user_id)
            
            # Re-render menu
            text, keyboard = await _build_channels_menu()
            await safe_edit_message_text(bot, user_id, admin_msg_id, text, parse_mode="HTML", reply_markup=keyboard)
            
        except Exception as e:
            logger.warning(f"Failed to add channel: {e}")
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back to Channels", callback_data="admin:channels")]])
            await safe_edit_message_text(
                bot, user_id, admin_msg_id,
                f"❌ <b>Invalid Channel ID or Access Denied</b>\n\n"
                f"• Error details: <code>{str(e)}</code>\n\n"
                "Please ensure the bot has been added to the channel as an <b>Administrator</b> with Posting permissions.",
                parse_mode="HTML",
                reply_markup=keyboard
            )

    elif state == "AWAITING_REMOVE_CHANNEL":
        category = data.get("category")
        try:
            channel_id = int(text_input)
            await db.delete_channel(channel_id, category)
            await fsm.clear_state(user_id)
            
            text, keyboard = await _build_channels_menu()
            await safe_edit_message_text(bot, user_id, admin_msg_id, text, parse_mode="HTML", reply_markup=keyboard)
        except Exception as e:
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back to Channels", callback_data="admin:channels")]])
            await safe_edit_message_text(
                bot, user_id, admin_msg_id,
                f"❌ <b>Error Removing Channel</b>\n\n<code>{str(e)}</code>",
                parse_mode="HTML",
                reply_markup=keyboard
            )

    elif state == "AWAITING_SET_FOOTER_TITLE":
        try:
            await db.set_setting("footer_title", text_input)
            await fsm.clear_state(user_id)
            
            text, keyboard = await _build_footers_menu()
            await safe_edit_message_text(bot, user_id, admin_msg_id, text, parse_mode="HTML", reply_markup=keyboard)
        except Exception as e:
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back to Footers", callback_data="admin:footers")]])
            await safe_edit_message_text(
                bot, user_id, admin_msg_id,
                f"❌ <b>Error Setting Title</b>\n\n<code>{str(e)}</code>",
                parse_mode="HTML",
                reply_markup=keyboard
            )

    elif state == "AWAITING_ADD_FOOTER_CHANNEL":
        category = data.get("category")
        try:
            # Add exactly as written (e.g. @channel or ID)
            await db.add_footer_channel(text_input, text_input, category)
            await fsm.clear_state(user_id)
            
            text, keyboard = await _build_footers_menu()
            await safe_edit_message_text(bot, user_id, admin_msg_id, text, parse_mode="HTML", reply_markup=keyboard)
        except Exception as e:
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back to Footers", callback_data="admin:footers")]])
            await safe_edit_message_text(
                bot, user_id, admin_msg_id,
                f"❌ <b>Error Adding Footer Channel</b>\n\n<code>{str(e)}</code>",
                parse_mode="HTML",
                reply_markup=keyboard
            )

    elif state == "AWAITING_REMOVE_FOOTER_CHANNEL":
        category = data.get("category")
        try:
            await db.delete_footer_channel(text_input, category)
            await fsm.clear_state(user_id)
            
            text, keyboard = await _build_footers_menu()
            await safe_edit_message_text(bot, user_id, admin_msg_id, text, parse_mode="HTML", reply_markup=keyboard)
        except Exception as e:
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back to Footers", callback_data="admin:footers")]])
            await safe_edit_message_text(
                bot, user_id, admin_msg_id,
                f"❌ <b>Error Removing Footer Link</b>\n\n<code>{str(e)}</code>",
                parse_mode="HTML",
                reply_markup=keyboard
            )

@safe_handler
@admin_only
async def handle_admin_forward_inputs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Extracts Telegram channel IDs automatically if an admin forwards a message from a target channel."""
    user_id = update.effective_user.id
    state, data = await fsm.get_state(user_id)
    bot = context.bot

    # Extract forwarded chat/channel safely
    forward_from_chat = getattr(update.message, "forward_from_chat", None)
    if not forward_from_chat and getattr(update.message, "forward_origin", None):
        from telegram import MessageOriginChannel
        if isinstance(update.message.forward_origin, MessageOriginChannel):
            forward_from_chat = update.message.forward_origin.chat

    if state == "AWAITING_ADD_CHANNEL" and forward_from_chat:
        # Delete user's forward message
        await safe_delete_message(bot, user_id, update.message.message_id)

        forwarded_chat = forward_from_chat
        admin_msg_id = data.get("admin_msg_id")
        category = data.get("category")

        if forwarded_chat.type == "channel":
            channel_id = forwarded_chat.id
            try:
                # Validate bot permissions in this channel
                chat = await bot.get_chat(channel_id)
                await db.add_channel(channel_id, chat.title, category)
                await fsm.clear_state(user_id)
                
                text, keyboard = await _build_channels_menu()
                await safe_edit_message_text(bot, user_id, admin_msg_id, text, parse_mode="HTML", reply_markup=keyboard)
            except Exception as e:
                keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back to Channels", callback_data="admin:channels")]])
                await safe_edit_message_text(
                    bot, user_id, admin_msg_id,
                    f"❌ <b>Access Denied to Forwarded Channel</b>\n\n"
                    f"Bot must be added as an <b>Administrator</b> inside the channel first.\n"
                    f"• Extracted Channel ID: <code>{channel_id}</code>\n"
                    f"• Error: <code>{str(e)}</code>",
                    parse_mode="HTML",
                    reply_markup=keyboard
                )
        else:
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back to Channels", callback_data="admin:channels")]])
            await safe_edit_message_text(
                bot, user_id, admin_msg_id,
                "⚠️ <b>Invalid Source:</b> The forwarded message is not from a Channel.",
                parse_mode="HTML",
                reply_markup=keyboard
            )

# --- Admin Menu Builders ---

def _build_main_menu() -> tuple[str, InlineKeyboardMarkup]:
    text = (
        "🛠 <b>Antigravity Bot Admin Panel</b>\n\n"
        "Welcome to your centralized administrative control panel. "
        "Use the options below to configure system nodes and monitor pipelines.\n\n"
        "• <b>Status:</b> Operational 🟢\n"
        "• <b>Admins:</b> Multiple Active 👥"
    )
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📡 Post Channels", callback_data="admin:channels"),
            InlineKeyboardButton("📺 Footer Settings", callback_data="admin:footers")
        ],
        [
            InlineKeyboardButton("⏳ Posting Queue", callback_data="admin:queue"),
            InlineKeyboardButton("📊 System Diagnostics", callback_data="admin:diagnostics")
        ],
        [
            InlineKeyboardButton("❌ Close Panel", callback_data="admin:close")
        ]
    ])
    return text, keyboard

async def _build_channels_menu() -> tuple[str, InlineKeyboardMarkup]:
    v_chans = await db.list_channels_by_category("vanced")
    c_chans = await db.list_channels_by_category("crunchy")
    
    text = (
        "📡 <b>Grouped Posting Channels</b>\n\n"
        "Below are your categorized channels where bot dispatches messages:\n\n"
        "<b>🎮 Vanced Games Group:</b>\n"
    )
    if not v_chans:
        text += "<i>No channels registered.</i>\n"
    else:
        for idx, chan in enumerate(v_chans, 1):
            text += f"{idx}. {chan['title']} (<code>{chan['channel_id']}</code>)\n"
            
    text += "\n<b>🍿 Crunchyroll Anime Group:</b>\n"
    if not c_chans:
        text += "<i>No channels registered.</i>\n"
    else:
        for idx, chan in enumerate(c_chans, 1):
            text += f"{idx}. {chan['title']} (<code>{chan['channel_id']}</code>)\n"
            
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Add Vanced", callback_data="admin:add_v"),
            InlineKeyboardButton("➕ Add Crunchy", callback_data="admin:add_c")
        ],
        [
            InlineKeyboardButton("➖ Remove Vanced", callback_data="admin:remove_v"),
            InlineKeyboardButton("➖ Remove Crunchy", callback_data="admin:remove_c")
        ],
        [
            InlineKeyboardButton("📋 Show Channels", callback_data="admin:show_p"),
            InlineKeyboardButton("🔙 Back", callback_data="admin:panel")
        ]
    ])
    return text, keyboard

async def _build_footers_menu() -> tuple[str, InlineKeyboardMarkup]:
    footer_title = await db.get_setting("footer_title", "Join Backup Channel 👇")
    v_footers = await db.list_footer_channels_by_category("vanced")
    c_footers = await db.list_footer_channels_by_category("crunchy")
    
    text = (
        "📺 <b>Footer Settings & Groups</b>\n\n"
        f"• <b>Footer Title:</b> <code>{footer_title}</code>\n\n"
        "<b>🎮 Vanced Games Footers:</b>\n"
    )
    if not v_footers:
        text += "<i>No footer links.</i>\n"
    else:
        for chan in v_footers:
            text += f"👉 <code>{chan['channel_id']}</code>\n"
            
    text += "\n<b>🍿 Crunchyroll Anime Footers:</b>\n"
    if not c_footers:
        text += "<i>No footer links.</i>\n"
    else:
        for chan in c_footers:
            text += f"👉 <code>{chan['channel_id']}</code>\n"
            
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✏️ Set Title", callback_data="admin:set_footer_title")
        ],
        [
            InlineKeyboardButton("➕ Add Vanced", callback_data="admin:add_footer_v"),
            InlineKeyboardButton("➕ Add Crunchy", callback_data="admin:add_footer_c")
        ],
        [
            InlineKeyboardButton("➖ Remove Vanced", callback_data="admin:remove_footer_v"),
            InlineKeyboardButton("➖ Remove Crunchy", callback_data="admin:remove_footer_c")
        ],
        [
            InlineKeyboardButton("📋 Show Footer", callback_data="admin:show_footer"),
            InlineKeyboardButton("🔙 Back", callback_data="admin:panel")
        ]
    ])
    return text, keyboard

async def _build_queue_menu() -> tuple[str, InlineKeyboardMarkup]:
    queued_items = await db.get_all_pending_queued_items(limit=10)
    text = (
        "⏳ <b>Active Posting Queue Status</b>\n\n"
        "Top 10 pending messages currently lined up in the posting manager:\n\n"
    )
    
    keyboard_buttons = []
    if not queued_items:
        text += "<i>No scheduled posts in the queue. All pipelines are clear.</i>"
    else:
        for idx, item in enumerate(queued_items, 1):
            media_icon = "📝" if item["media_type"] == "text" else "📷" if item["media_type"] == "photo" else "🎥"
            scheduled_in = int(item["scheduled_at"] - time.time())
            
            if scheduled_in > 0:
                if scheduled_in < 60:
                    time_label = f"in {scheduled_in}s"
                elif scheduled_in < 3600:
                    time_label = f"in {scheduled_in // 60}m"
                else:
                    time_label = f"in {scheduled_in // 3600}h {(scheduled_in % 3600) // 60}m"
            else:
                time_label = "Pending now"
            silent_label = "🔕 Silent" if item.get("disable_notification") else "🔔 Loud"
            
            text += (
                f"<b>#{item['queue_id']} | {media_icon} Target: {item['channel_id']} ({silent_label})</b>\n"
                f"• Timing: {time_label} | Retries: {item['retries']}/5\n\n"
            )
            keyboard_buttons.append([
                InlineKeyboardButton(f"❌ Cancel #{item['queue_id']}", callback_data=f"admin:cancel_q:{item['queue_id']}")
            ])

    keyboard_buttons.append([InlineKeyboardButton("◀️ Back to Main Menu", callback_data="admin:panel")])
    return text, InlineKeyboardMarkup(keyboard_buttons)

async def _build_diagnostics_menu() -> tuple[str, InlineKeyboardMarkup]:
    fsm_cache_size = len(fsm._cache)
    locks_size = len(fsm._locks)
    
    async with aiosqlite.connect(db.db_path) as conn:
        async with conn.execute("SELECT COUNT(*) FROM translation_cache") as cursor:
            cache_rows = (await cursor.fetchone())[0]
        async with conn.execute("SELECT COUNT(*) FROM posting_queue WHERE status = 'sent'") as cursor:
            sent_posts = (await cursor.fetchone())[0]
        async with conn.execute("SELECT COUNT(*) FROM posting_queue WHERE status = 'failed'") as cursor:
            failed_posts = (await cursor.fetchone())[0]

    text = (
        "📊 <b>System Diagnostics & Metrics</b>\n\n"
        f"• <b>FSM Session Cache:</b> {fsm_cache_size} active user(s)\n"
        f"• <b>State Concurrency Locks:</b> {locks_size} locks\n"
        f"• <b>Persistent Translation Cache:</b> {cache_rows} record(s)\n"
        f"• <b>Successful Queue Posts:</b> {sent_posts} post(s)\n"
        f"• <b>Failed Queue Posts:</b> {failed_posts} post(s)\n"
        f"• <b>Engine Status:</b> 100% Async Operational 🚀"
    )
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back to Main Menu", callback_data="admin:panel")]])
    return text, keyboard
