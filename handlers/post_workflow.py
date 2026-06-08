import re
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, MessageHandler, filters

from config import ADMIN_IDS, logger
from database import db
from services.fsm import fsm, States
from services.translation import translation_service
from services.queue_manager import queue_manager
from handlers.admin import is_admin, admin_only
from handlers.error_handler import (
    safe_handler, safe_callback, safe_edit_message_text,
    safe_edit_message_caption, safe_delete_message, safe_send_message
)

@safe_handler
@admin_only
async def handle_incoming_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Ingests raw incoming posts (text, photo, or video) from administrators.
    Triggers immediate language auto-translation and displays the Dynamic Preview.
    """
    user_id = update.effective_user.id
    bot = context.bot

    # Block ingestion if admin is in the middle of a configuration FSM state
    current_state, _ = await fsm.get_state(user_id)
    if current_state in ["AWAITING_ADD_CHANNEL", "AWAITING_REMOVE_CHANNEL", "AWAITING_SET_FOOTER_TITLE", "AWAITING_ADD_FOOTER_CHANNEL", "AWAITING_REMOVE_FOOTER_CHANNEL"]:
        # Let the admin config handler deal with it
        return

    # Delete the incoming admin message to keep clean interaction workspace
    await safe_delete_message(bot, user_id, update.message.message_id)

    # 1. Parse and extract post content
    original_text = ""
    media_file_id = None
    media_type = "text"

    if update.message.photo:
        media_type = "photo"
        media_file_id = update.message.photo[-1].file_id
        original_text = update.message.caption_html or ""
    elif update.message.video:
        media_type = "video"
        media_file_id = update.message.video.file_id
        original_text = update.message.caption_html or ""
    elif update.message.text:
        media_type = "text"
        original_text = update.message.text_html or ""
    else:
        # Unsupported media format
        await update.message.reply_text(
            "⚠️ <b>Unsupported Media Type</b>\n\n"
            "This bot only supports Text Posts, Image Captions, and Video Captions.",
            parse_mode="HTML"
        )
        return

    # Send a quick non-blocking status indicator
    status_msg = await bot.send_message(
        chat_id=user_id,
        text="🌐 <i>Ingesting post and auto-detecting language...</i>",
        parse_mode="HTML"
    )

    # 2. Run high-fidelity translation to English prior to preview generation
    translated_text, detected_lang, was_translated = await translation_service.translate_html(original_text)

    # 3. Clean up any previous active/orphaned previews to prevent leaks
    _, old_data = await fsm.get_state(user_id)
    old_preview_id = old_data.get("preview_message_id")
    if old_preview_id:
        await safe_delete_message(bot, user_id, old_preview_id)

    # Delete status indicator
    await safe_delete_message(bot, user_id, status_msg.message_id)

    # 4. Populate initial draft state data
    draft_data = {
        "original_text": original_text,
        "translated_text": translated_text,
        "media_file_id": media_file_id,
        "media_type": media_type,
        "detected_lang": detected_lang,
        "was_translated": was_translated,
        "footer_enabled": True,       # Enabled by default
        "silent_mode": False,         # Loud notifications by default
        "buttons_config": [],         # Inline URL buttons
        "preview_message_id": None,
        "sched_menu_state": None,     # Scheduling sub-menu state (None, 'target_select', 'delay_select')
        "sched_category": None        # Scheduled target group (vanced, crunchy, both)
    }

    # Set FSM to Preview state
    await fsm.set_state(user_id, States.PREVIEW_GENERATED, draft_data)

    # 5. Generate and send dynamic preview message
    await _send_new_preview(bot, user_id, draft_data)

# --- Callback Router for Dynamic Preview Panel ---

@safe_callback
@admin_only
async def post_callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processes callback actions triggered by the dynamic preview control buttons."""
    query = update.callback_query
    data = query.data
    user_id = update.effective_user.id
    bot = context.bot

    # Get active draft state
    state, draft = await fsm.get_state(user_id)
    if state != States.PREVIEW_GENERATED or not draft:
        # Stale workflow interaction
        await query.answer("⚠️ This draft session has expired. Send a new message to start.", show_alert=True)
        await safe_delete_message(bot, user_id, query.message.message_id)
        return

    # Toggle silent/loud posting mode
    if data == "post:toggle_silent":
        draft["silent_mode"] = not draft.get("silent_mode", False)
        await fsm.set_state(user_id, States.PREVIEW_GENERATED, draft)
        await _update_existing_preview(bot, user_id, draft)
        await query.answer("Notification mode updated.")

    # Toggle Footer inclusion
    elif data == "post:toggle_footer":
        draft["footer_enabled"] = not draft.get("footer_enabled", True)
        await fsm.set_state(user_id, States.PREVIEW_GENERATED, draft)
        await _update_existing_preview(bot, user_id, draft)
        await query.answer("Footer toggle updated.")

    # Trigger Awaiting Custom Buttons FSM state
    elif data == "post:edit_buttons":
        await fsm.set_state(user_id, States.EDITING_BUTTONS, draft)
        
        # Guide user on button format
        guide_msg = await bot.send_message(
            chat_id=user_id,
            text=(
                "🎹 <b>Add Custom Inline Buttons</b>\n\n"
                "Please send your custom URL button configurations below.\n"
                "Syntax: <code>Name | URL</code> or <code>Name -> URL</code>\n\n"
                "<b>Example (Single Button):</b>\n"
                "<code>Google | google.com</code>\n\n"
                "<b>Example (Multiple Buttons & Rows):</b>\n"
                "<code>Google -> google.com | GitHub -> github.com</code>\n"
                "<code>Support Chat -> t.me/support</code>\n\n"
                "<i>Send <code>none</code> or an empty message to clear custom buttons.</i>"
            ),
            parse_mode="HTML"
        )
        # Record guide message ID to delete later
        draft["btn_guide_msg_id"] = guide_msg.message_id
        await fsm.set_state(user_id, States.EDITING_BUTTONS, draft)
        await query.answer()

    # Trigger Caption Editing FSM state
    elif data == "post:edit_caption":
        await fsm.set_state(user_id, States.EDITING_CAPTION, draft)
        
        guide_msg = await bot.send_message(
            chat_id=user_id,
            text=(
                "✏️ <b>Edit Caption Text</b>\n\n"
                "Please send the new caption text below.\n"
                "Emojis and HTML text formatting are supported."
            ),
            parse_mode="HTML"
        )
        draft["caption_guide_msg_id"] = guide_msg.message_id
        await fsm.set_state(user_id, States.EDITING_CAPTION, draft)
        await query.answer()

    # Trigger Scheduler sub-menu: Group Target Selection
    elif data == "post:schedule":
        draft["sched_menu_state"] = "target_select"
        await fsm.set_state(user_id, States.PREVIEW_GENERATED, draft)
        await _update_existing_preview(bot, user_id, draft)
        await query.answer()

    # Return from scheduling back to main preview
    elif data == "post:sched_back":
        draft["sched_menu_state"] = None
        draft["sched_category"] = None
        await fsm.set_state(user_id, States.PREVIEW_GENERATED, draft)
        await _update_existing_preview(bot, user_id, draft)
        await query.answer()

    # Trigger Scheduler sub-menu: Delay Duration Selection
    elif data.startswith("post:sched_target:"):
        sched_cat = data.split(":")[-1]
        draft["sched_category"] = sched_cat
        draft["sched_menu_state"] = "delay_select"
        await fsm.set_state(user_id, States.PREVIEW_GENERATED, draft)
        await _update_existing_preview(bot, user_id, draft)
        await query.answer()

    # Return from delay select back to target category select
    elif data == "post:sched_target_back":
        draft["sched_category"] = None
        draft["sched_menu_state"] = "target_select"
        await fsm.set_state(user_id, States.PREVIEW_GENERATED, draft)
        await _update_existing_preview(bot, user_id, draft)
        await query.answer()

    # Trigger Custom Scheduler Delay Input state
    elif data == "post:sched_delay:custom":
        await fsm.set_state(user_id, States.AWAITING_SCHEDULE_TIME, draft)
        
        guide_msg = await bot.send_message(
            chat_id=user_id,
            text=(
                "✏️ <b>Enter Custom Delay Duration</b>\n\n"
                "Please send the delay duration below.\n"
                "<b>Examples:</b>\n"
                "• <code>45m</code> (45 minutes)\n"
                "• <code>2h</code> (2 hours)\n"
                "• <code>12h</code> (12 hours)\n"
                "• <code>1d</code> (1 day)\n"
                "• <code>90s</code> (90 seconds)"
            ),
            parse_mode="HTML"
        )
        draft["sched_guide_msg_id"] = guide_msg.message_id
        await fsm.set_state(user_id, States.AWAITING_SCHEDULE_TIME, draft)
        await query.answer()

    # Execute quick scheduler options
    elif data.startswith("post:sched_delay:"):
        delay_seconds = float(data.split(":")[-1])
        await safe_delete_message(bot, user_id, query.message.message_id)
        await _execute_queue_scheduling(bot, user_id, draft, delay_seconds=delay_seconds)
        await query.answer("Post scheduled successfully!")

    # Immediate Posting actions
    elif data in ["post:vanced", "post:crunchy", "post:both"]:
        category_targets = []
        if data == "post:vanced":
            category_targets.append("vanced")
        elif data == "post:crunchy":
            category_targets.append("crunchy")
        elif data == "post:both":
            category_targets.extend(["vanced", "crunchy"])

        # Fetch destination channels
        channels = []
        for cat in category_targets:
            cat_chans = await db.list_channels_by_category(cat)
            for c in cat_chans:
                channels.append((c, cat))

        if not channels:
            await query.answer("❌ No active channels configured in these groups!", show_alert=True)
            return

        silent = draft.get("silent_mode", False)

        # Queue posts for each destination channel
        for chan, cat in channels:
            # Dynamically compile the text specifically for this channel group footer
            compiled_text = await _compile_final_text(draft, category=cat)
            
            await db.add_to_queue(
                user_id=user_id,
                content={"text": compiled_text, "buttons": draft["buttons_config"]},
                media_file_id=draft["media_file_id"],
                media_type=draft["media_type"],
                channel_id=chan["channel_id"],
                delay_seconds=0.0,
                disable_notification=silent
            )

        # Clear state and clean preview
        await fsm.clear_state(user_id)
        await safe_delete_message(bot, user_id, query.message.message_id)
        await query.answer("✅ Successfully queued to target channels!", show_alert=False)
        
        target_name = "Both Groups" if len(category_targets) > 1 else category_targets[0].capitalize()
        await bot.send_message(
            chat_id=user_id,
            text=f"🚀 <b>Post successfully queued for {target_name} Channels!</b>",
            parse_mode="HTML"
        )

    # Cancel and Clear Draft State safely
    elif data == "post:cancel":
        await fsm.clear_state(user_id)
        await safe_delete_message(bot, user_id, query.message.message_id)
        await query.answer("Draft cancelled.")

    # Direct Schedule Cancellation Hook
    elif data.startswith("post:cancel_sched:"):
        ids_str = data.split(":")[-1]
        q_ids = [int(x) for x in ids_str.split("_") if x.isdigit()]
        
        cancelled_count = 0
        for q_id in q_ids:
            await db.cancel_queue_item(q_id)
            cancelled_count += 1
            
        await query.answer("Scheduled post cancelled successfully!", show_alert=True)
        await safe_edit_message_text(
            bot, user_id, query.message.message_id,
            text=f"❌ <b>Scheduled post has been cancelled successfully!</b> (Removed {cancelled_count} pending channel tasks)",
            parse_mode="HTML"
        )

# --- FSM Input Receivers ---

def parse_buttons(raw_input: str) -> list:
    """Parses text configurations of buttons submitted by admins, supporting multiple rows and buttons."""
    if raw_input.lower().strip() == "none" or not raw_input.strip():
        return []
    
    buttons_config = []
    lines = raw_input.strip().split("\n")
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        row_buttons = []
        # Check if this line uses the '->' format
        if "->" in line:
            parts = line.split("|")
            for part in parts:
                part = part.strip()
                if not part:
                    continue
                if "->" in part:
                    name, url = part.split("->", 1)
                    name = name.strip()
                    url = url.strip()
                    if name and url:
                        if not url.startswith(("http://", "https://", "tg://")):
                            url = "https://" + url
                        row_buttons.append({"text": name, "url": url})
        else:
            # Standard format or custom format using '|'
            parts = [x.strip() for x in line.split("|") if x.strip()]
            if len(parts) == 2:
                name, url = parts[0], parts[1]
                if not url.startswith(("http://", "https://", "tg://")):
                    url = "https://" + url
                row_buttons.append({"text": name, "url": url})
            elif len(parts) > 2 and len(parts) % 2 == 0:
                # Even number of parts, assume name | url | name | url
                for i in range(0, len(parts), 2):
                    name = parts[i]
                    url = parts[i+1]
                    if not url.startswith(("http://", "https://", "tg://")):
                        url = "https://" + url
                    row_buttons.append({"text": name, "url": url})
            elif len(parts) == 1:
                val = parts[0]
                if val.startswith(("http://", "https://", "tg://")) or "." in val:
                    url = val if val.startswith(("http://", "https://", "tg://")) else "https://" + val
                    row_buttons.append({"text": val, "url": url})
        
        if row_buttons:
            buttons_config.append(row_buttons)
            
    return buttons_config

@safe_handler
@admin_only
async def handle_custom_buttons_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Parses text configurations of buttons submitted by admins, returning to the preview menu."""
    user_id = update.effective_user.id
    state, draft = await fsm.get_state(user_id)
    bot = context.bot

    if state != States.EDITING_BUTTONS or not draft:
        return

    # Delete admin's submission and button guide message to clean history
    await safe_delete_message(bot, user_id, update.message.message_id)
    guide_id = draft.get("btn_guide_msg_id")
    if guide_id:
        await safe_delete_message(bot, user_id, guide_id)

    raw_input = update.message.text.strip()
    buttons_config = parse_buttons(raw_input)

    if raw_input.lower() != "none" and not buttons_config:
        await bot.send_message(chat_id=user_id, text="❌ Invalid button format. No buttons were added.")
    elif buttons_config:
        total_buttons = sum(len(row) for row in buttons_config)
        await bot.send_message(chat_id=user_id, text=f"✅ Configured {total_buttons} button(s) successfully!")

    # Save parsed config back to state
    draft["buttons_config"] = buttons_config
    if "btn_guide_msg_id" in draft:
        del draft["btn_guide_msg_id"]

    await fsm.set_state(user_id, States.PREVIEW_GENERATED, draft)
    await _update_existing_preview(bot, user_id, draft)

@safe_handler
@admin_only
async def handle_caption_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processes textual inputs from admins when FSM is active for editing caption."""
    user_id = update.effective_user.id
    state, draft = await fsm.get_state(user_id)
    bot = context.bot

    if state != States.EDITING_CAPTION or not draft:
        return

    # Delete admin's submission and caption guide message
    await safe_delete_message(bot, user_id, update.message.message_id)
    guide_id = draft.get("caption_guide_msg_id")
    if guide_id:
        await safe_delete_message(bot, user_id, guide_id)

    new_caption = update.message.text_html.strip()

    # Update draft
    draft["translated_text"] = new_caption
    draft["was_translated"] = False
    
    if "caption_guide_msg_id" in draft:
        del draft["caption_guide_msg_id"]

    await fsm.set_state(user_id, States.PREVIEW_GENERATED, draft)
    await _update_existing_preview(bot, user_id, draft)

@safe_handler
@admin_only
async def handle_schedule_time_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processes custom delay duration inputs from admins."""
    user_id = update.effective_user.id
    state, draft = await fsm.get_state(user_id)
    bot = context.bot

    if state != States.AWAITING_SCHEDULE_TIME or not draft:
        return

    # Delete admin's submission and schedule guide message
    await safe_delete_message(bot, user_id, update.message.message_id)
    guide_id = draft.get("sched_guide_msg_id")
    if guide_id:
        await safe_delete_message(bot, user_id, guide_id)

    raw_input = update.message.text.strip()
    try:
        delay_seconds = _parse_custom_delay(raw_input)
        
        # Deleting existing preview message prior to execution
        preview_id = draft.get("preview_message_id")
        if preview_id:
            await safe_delete_message(bot, user_id, preview_id)

        # Execute queue scheduling
        await _execute_queue_scheduling(bot, user_id, draft, delay_seconds=delay_seconds)
        
    except Exception as e:
        # Send error alert and return to normal preview
        await bot.send_message(
            chat_id=user_id,
            text=f"❌ <b>Invalid Delay Duration:</b> {str(e)}\n\nReturning to preview panel.",
            parse_mode="HTML"
        )
        if "sched_guide_msg_id" in draft:
            del draft["sched_guide_msg_id"]
        draft["sched_menu_state"] = None
        await fsm.set_state(user_id, States.PREVIEW_GENERATED, draft)
        await _update_existing_preview(bot, user_id, draft)

# --- Internal Scheduling Helper Routines ---

async def _execute_queue_scheduling(bot, user_id: int, draft: dict, delay_seconds: float) -> bool:
    """Adds the drafted post to the database posting queue with the specified delay."""
    category_targets = []
    cat = draft.get("sched_category", "vanced")
    if cat == "vanced":
        category_targets.append("vanced")
    elif cat == "crunchy":
        category_targets.append("crunchy")
    elif cat == "both":
        category_targets.extend(["vanced", "crunchy"])

    # Fetch destination channels
    channels = []
    for c_cat in category_targets:
        cat_chans = await db.list_channels_by_category(c_cat)
        for c in cat_chans:
            channels.append((c, c_cat))

    if not channels:
        await bot.send_message(
            chat_id=user_id,
            text="❌ <b>Scheduling Failed:</b> No active channels configured in these categories!"
        )
        # Clear state
        await fsm.clear_state(user_id)
        return False

    silent = draft.get("silent_mode", False)

    added_ids = []
    # Queue posts for each destination channel with delay
    for chan, c_cat in channels:
        compiled_text = await _compile_final_text(draft, category=c_cat)
        
        q_id = await db.add_to_queue(
            user_id=user_id,
            content={"text": compiled_text, "buttons": draft["buttons_config"]},
            media_file_id=draft["media_file_id"],
            media_type=draft["media_type"],
            channel_id=chan["channel_id"],
            delay_seconds=delay_seconds,
            disable_notification=silent
        )
        if q_id:
            added_ids.append(str(q_id))

    # Clear state
    await fsm.clear_state(user_id)
    
    # Send schedule confirmation
    delay_str = _format_delay_duration(delay_seconds)
    target_name = "Both Groups" if len(category_targets) > 1 else category_targets[0].capitalize()
    
    ids_str = "_".join(added_ids)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancel Scheduled Post", callback_data=f"post:cancel_sched:{ids_str}")]
    ])

    await bot.send_message(
        chat_id=user_id,
        text=(
            f"📅 <b>Post Scheduled Successfully!</b>\n\n"
            f"• <b>Target:</b> {target_name} Channels\n"
            f"• <b>Delay:</b> {delay_str}\n"
            f"• <b>Status:</b> Queued for background delivery."
        ),
        parse_mode="HTML",
        reply_markup=keyboard
    )
    return True

def _parse_custom_delay(input_str: str) -> float:
    """Parses delay expressions like '45m', '2h', '1d' into seconds."""
    match = re.match(r"^(\d+)\s*(s|m|h|d|min|hour|day|sec)?$", input_str.lower().strip())
    if not match:
        raise ValueError("Invalid duration format. Use numbers followed by s, m, h, or d (e.g. 45m, 2h).")
    
    value = int(match.group(1))
    unit = match.group(2) or "m"  # Default to minutes
    
    if unit in ["s", "sec"]:
        return float(value)
    elif unit in ["m", "min"]:
        return float(value * 60)
    elif unit in ["h", "hour"]:
        return float(value * 3600)
    elif unit in ["d", "day"]:
        return float(value * 86400)
    
    return float(value * 60)

def _format_delay_duration(seconds: float) -> str:
    """Helper to convert float seconds back to dynamic human-readable string."""
    if seconds < 60:
        return f"{int(seconds)} seconds"
    elif seconds < 3600:
        return f"{int(seconds // 60)} minutes"
    elif seconds < 86400:
        return f"{int(seconds // 3600)} hours"
    else:
        return f"{int(seconds // 86400)} days"

# --- Internal Post UI Renderers ---

async def _compile_final_text(draft: dict, category: str = "vanced") -> str:
    """Combines translated text body with custom category footer if toggled on."""
    base_text = f"👇👇👇\n\n{draft['translated_text']}"
    
    footer_enabled = draft.get("footer_enabled", True)
    if footer_enabled:
        footer_title = await db.get_setting("footer_title", "Join Backup Channel 👇")
        footer_chans = await db.list_footer_channels_by_category(category)
        if footer_chans:
            base_text += f"\n\n{footer_title}\n\n"
            for f in footer_chans:
                base_text += f"👉 {f['channel_id']}\n"
    return base_text.strip()

async def _build_preview_markup(draft: dict) -> InlineKeyboardMarkup:
    """Builds the dynamic interactive menu buttons below the preview message."""
    sched_state = draft.get("sched_menu_state")

    # 1. Custom preview buttons (makes your custom buttons show in bot preview before posting)
    custom_btns = []
    for row in draft["buttons_config"]:
        custom_row = []
        for btn in row:
            custom_row.append(InlineKeyboardButton(btn["text"], url=btn["url"]))
        if custom_row:
            custom_btns.append(custom_row)
        
    if sched_state == "target_select":
        # Target Category Select for scheduling
        control_btns = [
            [
                InlineKeyboardButton("🎮 Vanced Games", callback_data="post:sched_target:vanced"),
                InlineKeyboardButton("🍿 Crunchyroll Anime", callback_data="post:sched_target:crunchy")
            ],
            [InlineKeyboardButton("🚀 Both Groups", callback_data="post:sched_target:both")],
            [InlineKeyboardButton("◀️ Back to Preview", callback_data="post:sched_back")]
        ]
        return InlineKeyboardMarkup(custom_btns + control_btns)

    elif sched_state == "delay_select":
        # Delay options select
        control_btns = [
            [
                InlineKeyboardButton("⏱ 5 Min", callback_data="post:sched_delay:300"),
                InlineKeyboardButton("⏱ 15 Min", callback_data="post:sched_delay:900")
            ],
            [
                InlineKeyboardButton("⏱ 1 Hour", callback_data="post:sched_delay:3600"),
                InlineKeyboardButton("⏱ 3 Hours", callback_data="post:sched_delay:10800")
            ],
            [
                InlineKeyboardButton("⏱ 6 Hours", callback_data="post:sched_delay:21600"),
                InlineKeyboardButton("⏱ 12 Hours", callback_data="post:sched_delay:43200")
            ],
            [
                InlineKeyboardButton("⏱ 24 Hours", callback_data="post:sched_delay:86400"),
                InlineKeyboardButton("✏️ Custom Delay", callback_data="post:sched_delay:custom")
            ],
            [InlineKeyboardButton("◀️ Back", callback_data="post:sched_target_back")]
        ]
        return InlineKeyboardMarkup(custom_btns + control_btns)

    else:
        # Standard Menu
        silent = draft.get("silent_mode", False)
        footer_enabled = draft.get("footer_enabled", True)

        control_btns = [
            [InlineKeyboardButton("🔕 Silent ON" if silent else "🔔 Silent OFF", callback_data="post:toggle_silent")],
            [InlineKeyboardButton("📺 Footer ON" if footer_enabled else "📺 Footer OFF", callback_data="post:toggle_footer")],
            [InlineKeyboardButton("➕ Add Button", callback_data="post:edit_buttons")],
            [InlineKeyboardButton("✏️ Edit Caption", callback_data="post:edit_caption")],
            [
                InlineKeyboardButton("🎮 Vanced Games", callback_data="post:vanced"),
                InlineKeyboardButton("🍿 Crunchyroll Anime", callback_data="post:crunchy"),
            ],
            [
                InlineKeyboardButton("🚀 Send to Both", callback_data="post:both"),
                InlineKeyboardButton("📅 Schedule Post", callback_data="post:schedule")
            ],
            [InlineKeyboardButton("❌ Cancel", callback_data="post:cancel")]
        ]
        return InlineKeyboardMarkup(custom_btns + control_btns)

async def _send_new_preview(bot, user_id: int, draft: dict):
    """Sends a fresh preview message layout and registers its ID to FSM state."""
    # Preview with "vanced" footers by default
    parse_text = await _compile_final_text(draft, category="vanced")
    keyboard = await _build_preview_markup(draft)

    # Formatting header indicator based on FSM scheduling state
    sched_state = draft.get("sched_menu_state")
    if sched_state == "target_select":
        header = (
            f"<b>✨ SCHEDULE POST ➡️ SELECT GROUP</b>\n"
            f"<i>Please choose the target channel group below.</i>\n"
            f"━━━━━━━━━━━━━━━━━━━\n\n"
        )
    elif sched_state == "delay_select":
        cat_name = draft.get("sched_category", "vanced").upper()
        header = (
            f"<b>✨ SCHEDULE POST ➡️ SELECT DELAY</b>\n"
            f"<i>Target Group: {cat_name}</i>\n"
            f"<i>Please select the publishing delay or specify custom duration.</i>\n"
            f"━━━━━━━━━━━━━━━━━━━\n\n"
        )
    else:
        header = (
            f"<b>✨ DRAFT POST PREVIEW</b>\n"
            f"<i>Language: {draft['detected_lang'].upper()} ➡️ EN | Translated: {'Yes' if draft['was_translated'] else 'No'}</i>\n"
            f"━━━━━━━━━━━━━━━━━━━\n\n"
        )

    full_display_text = f"{header}{parse_text}"

    preview_msg = None
    try:
        if draft["media_type"] == "text":
            preview_msg = await bot.send_message(
                chat_id=user_id,
                text=full_display_text,
                parse_mode="HTML",
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
        elif draft["media_type"] == "photo":
            preview_msg = await bot.send_photo(
                chat_id=user_id,
                photo=draft["media_file_id"],
                caption=full_display_text,
                parse_mode="HTML",
                reply_markup=keyboard
            )
        elif draft["media_type"] == "video":
            preview_msg = await bot.send_video(
                chat_id=user_id,
                video=draft["media_file_id"],
                caption=full_display_text,
                parse_mode="HTML",
                reply_markup=keyboard
            )
    except Exception as e:
        logger.error(f"Failed to send initial post preview: {e}", exc_info=True)
        try:
            preview_msg = await bot.send_message(
                chat_id=user_id,
                text=f"{full_display_text}\n\n<i>⚠️ Media preview failed: {str(e)}</i>",
                parse_mode="HTML",
                reply_markup=keyboard
            )
        except Exception:
            pass

    if preview_msg:
        # Update FSM with the active preview message ID
        draft["preview_message_id"] = preview_msg.message_id
        await fsm.set_state(user_id, States.PREVIEW_GENERATED, draft)

async def _update_existing_preview(bot, user_id: int, draft: dict):
    """Dynamic update - edits the active preview message in-place to avoid duplication."""
    preview_id = draft.get("preview_message_id")
    if not preview_id:
        # Send new preview instead
        await _send_new_preview(bot, user_id, draft)
        return

    parse_text = await _compile_final_text(draft, category="vanced")
    keyboard = await _build_preview_markup(draft)

    sched_state = draft.get("sched_menu_state")
    if sched_state == "target_select":
        header = (
            f"<b>✨ SCHEDULE POST ➡️ SELECT GROUP</b>\n"
            f"<i>Please choose the target channel group below.</i>\n"
            f"━━━━━━━━━━━━━━━━━━━\n\n"
        )
    elif sched_state == "delay_select":
        cat_name = draft.get("sched_category", "vanced").upper()
        header = (
            f"<b>✨ SCHEDULE POST ➡️ SELECT DELAY</b>\n"
            f"<i>Target Group: {cat_name}</i>\n"
            f"<i>Please select the publishing delay or specify custom duration.</i>\n"
            f"━━━━━━━━━━━━━━━━━━━\n\n"
        )
    else:
        header = (
            f"<b>✨ DRAFT POST PREVIEW</b>\n"
            f"<i>Language: {draft['detected_lang'].upper()} ➡️ EN | Translated: {'Yes' if draft['was_translated'] else 'No'}</i>\n"
            f"━━━━━━━━━━━━━━━━━━━\n\n"
        )
        
    full_display_text = f"{header}{parse_text}"

    success = False
    if draft["media_type"] == "text":
        success = await safe_edit_message_text(
            bot, chat_id=user_id, message_id=preview_id,
            text=full_display_text, parse_mode="HTML",
            reply_markup=keyboard, disable_web_page_preview=True
        )
    else:
        success = await safe_edit_message_caption(
            bot, chat_id=user_id, message_id=preview_id,
            caption=full_display_text, parse_mode="HTML",
            reply_markup=keyboard
        )

    if not success:
        logger.info(f"Failed to edit existing preview #{preview_id} for user {user_id}. Creating new preview.")
        await _send_new_preview(bot, user_id, draft)
