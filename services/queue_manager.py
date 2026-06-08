import asyncio
import time
from typing import Dict, Any, Optional
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError, RetryAfter, TimedOut, NetworkError, BadRequest, Forbidden

from config import (
    logger, QUEUE_CHECK_INTERVAL, MAX_RETRIES, RETRY_INITIAL_DELAY, RETRY_MAX_DELAY,
    TELEGRAM_FLOOD_LIMIT_PER_CHAT, TELEGRAM_FLOOD_LIMIT_GLOBAL
)
from database import db

class QueueManager:
    def __init__(self):
        self.bot: Optional[Bot] = None
        self._worker_task: Optional[asyncio.Task] = None
        # Track last send timestamps to guarantee rate limit boundaries
        self._last_send_global = 0.0
        self._last_send_per_chat: Dict[int, float] = {}
        self._worker_lock = asyncio.Lock()

    def set_bot(self, bot: Bot):
        """Initializes the Telegram bot instance for queue delivery."""
        self.bot = bot
        logger.info("Bot instance registered to QueueManager.")

    def start(self):
        """Starts the background queue worker process."""
        if not self._worker_task or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker_loop())
            logger.info("Background posting Queue Manager started.")

    async def stop(self):
        """Stops the queue worker gracefully."""
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            logger.info("Background posting Queue Manager stopped.")

    async def _worker_loop(self):
        """Infinite worker loop polling the SQLite database for pending messages."""
        while True:
            try:
                if not self.bot:
                    await asyncio.sleep(1.0)
                    continue

                # Query database for next batch of due posts
                queued_items = await db.get_next_queued_items(limit=5)
                
                for item in queued_items:
                    # Double-check rate limit before processing each item
                    await self._enforce_rate_limits(item["channel_id"])
                    await self._process_item(item)
                    
            except asyncio.CancelledError:
                logger.info("Queue worker received cancellation request.")
                break
            except Exception as e:
                logger.error(f"Uncaught exception in queue worker loop: {e}", exc_info=True)
                await asyncio.sleep(5.0)

            await asyncio.sleep(QUEUE_CHECK_INTERVAL)

    async def _enforce_rate_limits(self, chat_id: int):
        """Applies pauses to comply with Telegram's global and per-channel message rate limits."""
        now = time.time()

        # 1. Enforce global rate limit (max 30 sends/sec -> ~0.033s gap)
        elapsed_global = now - self._last_send_global
        if elapsed_global < TELEGRAM_FLOOD_LIMIT_GLOBAL:
            sleep_time = TELEGRAM_FLOOD_LIMIT_GLOBAL - elapsed_global
            await asyncio.sleep(sleep_time)

        # 2. Enforce chat-specific limit (max 1 send/sec per chat -> ~1s gap)
        now = time.time()  # re-evaluate timestamp
        last_chat_send = self._last_send_per_chat.get(chat_id, 0.0)
        elapsed_chat = now - last_chat_send
        if elapsed_chat < TELEGRAM_FLOOD_LIMIT_PER_CHAT:
            sleep_time = TELEGRAM_FLOOD_LIMIT_PER_CHAT - elapsed_chat
            await asyncio.sleep(sleep_time)

        # Update timestamps
        now_final = time.time()
        self._last_send_global = now_final
        self._last_send_per_chat[chat_id] = now_final

    async def _process_item(self, item: Dict[str, Any]):
        """Processes a single queue item, executing the API send and performing error recovery/retries."""
        queue_id = item["queue_id"]
        channel_id = item["channel_id"]
        media_file_id = item["media_file_id"]
        media_type = item["media_type"]
        retries = item["retries"]
        content = item["content"]

        text = content.get("text", "")
        buttons_config = content.get("buttons", [])

        # Parse inline keyboard
        reply_markup = self._build_keyboard(buttons_config)

        # Retrieve disable_notification flag
        disable_notification = item.get("disable_notification", False)

        logger.info(f"Processing queue item #{queue_id} (Channel: {channel_id}, Retries: {retries}, Silent: {disable_notification})...")

        try:
            # Execute standard non-blocking Telegram send
            if media_type == "text":
                await self.bot.send_message(
                    chat_id=channel_id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                    disable_web_page_preview=False,
                    disable_notification=disable_notification
                )
            elif media_type == "photo":
                await self.bot.send_photo(
                    chat_id=channel_id,
                    photo=media_file_id,
                    caption=text,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                    disable_notification=disable_notification
                )
            elif media_type == "video":
                await self.bot.send_video(
                    chat_id=channel_id,
                    video=media_file_id,
                    caption=text,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                    disable_notification=disable_notification
                )
            else:
                raise ValueError(f"Unsupported media type: {media_type}")

            # Mark as sent
            await db.update_queue_status(queue_id, "sent")
            logger.info(f"Queue item #{queue_id} posted successfully to channel {channel_id}.")

        except RetryAfter as e:
            # Telegram rate limit exceeded, block worker and schedule retry immediately
            retry_delay = float(e.retry_after) + 1.0
            logger.warning(f"Telegram rate limit hit. Pausing for {retry_delay}s. Item #{queue_id} rescheduled.")
            # Update state with retry increment but mark as pending with future schedule
            await db.update_queue_status(
                queue_id=queue_id,
                status="pending",
                error_message=f"Rate limited: Retry after {e.retry_after}s",
                increment_retry=True
            )
            # Push schedule forward
            # We will sleep here to halt the loop and give the API time to cool down
            await asyncio.sleep(retry_delay)

        except (TimedOut, NetworkError) as e:
            # Ephemeral network issue, retry with exponential backoff
            logger.warning(f"Network error sending item #{queue_id}: {e}. Retrying...")
            await self._handle_retry(queue_id, retries, str(e))

        except (BadRequest, Forbidden) as e:
            # Permanent configuration error (e.g. ChatNotFound, Forbidden - Bot kicked, Media ID bad, Caption too long)
            logger.error(f"Permanent Telegram API failure on item #{queue_id}: {e}")
            await db.update_queue_status(
                queue_id=queue_id,
                status="failed",
                error_message=f"Permanent Error: {str(e)}"
            )
            # Notify admins of failure
            await self._notify_admins_of_failure(queue_id, channel_id, str(e))

        except Exception as e:
            # Any other uncaught exceptions, treat as potential temporary and retry
            logger.error(f"Unexpected error processing item #{queue_id}: {e}", exc_info=True)
            await self._handle_retry(queue_id, retries, str(e))

    async def _handle_retry(self, queue_id: int, current_retries: int, last_error: str):
        """Calculates backoff delay, updates item scheduled time, and marks failed if retries exceeded."""
        if current_retries >= MAX_RETRIES:
            logger.error(f"Queue item #{queue_id} exceeded maximum retries. Marking as failed.")
            await db.update_queue_status(
                queue_id=queue_id,
                status="failed",
                error_message=f"Exceeded max retries. Last error: {last_error}"
            )
            return

        # Calculate exponential backoff
        backoff = min(RETRY_INITIAL_DELAY * (2 ** current_retries), RETRY_MAX_DELAY)
        logger.info(f"Scheduling retry #{current_retries + 1} for item #{queue_id} in {backoff} seconds.")
        
        scheduled_at = time.time() + backoff
        # Increment retry and reset state to pending with delay
        await db.update_queue_status(
            queue_id=queue_id,
            status="pending",
            error_message=last_error,
            increment_retry=True,
            scheduled_at=scheduled_at
        )

    def _build_keyboard(self, buttons_config: list) -> Optional[InlineKeyboardMarkup]:
        """Constructs an InlineKeyboardMarkup from JSON stored buttons data."""
        if not buttons_config:
            return None

        keyboard = []
        for row in buttons_config:
            keyboard_row = []
            for btn in row:
                keyboard_row.append(
                    InlineKeyboardButton(text=btn["text"], url=btn["url"])
                )
            if keyboard_row:
                keyboard.append(keyboard_row)

        return InlineKeyboardMarkup(keyboard) if keyboard else None

    async def _notify_admins_of_failure(self, queue_id: int, channel_id: int, error: str):
        """Alerts administrators that a queued channel post failed permanently."""
        from config import ADMIN_IDS
        if not self.bot or not ADMIN_IDS:
            return

        for admin_id in ADMIN_IDS:
            try:
                await self.bot.send_message(
                    chat_id=admin_id,
                    text=(
                        f"❌ <b>Posting Queue Failure Alert</b>\n\n"
                        f"• <b>Queue ID:</b> #{queue_id}\n"
                        f"• <b>Target Channel:</b> {channel_id}\n"
                        f"• <b>Reason:</b> <code>{error}</code>\n\n"
                        f"<i>This item has been taken out of the queue. Please verify bot administrator permissions or formatting.</i>"
                    ),
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Failed to send failure notification to admin {admin_id}: {e}")

# Singleton Queue Manager
queue_manager = QueueManager()
