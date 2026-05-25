import os
import time
import asyncio
from config import logger, DATABASE_PATH

# Chat/Channel ID where the database backups will be sent and pinned
BACKUP_CHAT_ID = os.getenv("BACKUP_CHAT_ID", "").strip()

class BackupManager:
    def __init__(self):
        self.last_backup_mtime = 0.0
        self.bot = None

    def set_bot(self, bot):
        """Passes the Telegram Bot instance to the backup manager."""
        self.bot = bot

    async def restore_backup(self) -> bool:
        """
        Retrieves the latest pinned bot.db document from the backup channel on startup.
        Downloads it to DATABASE_PATH before the DB manager initializes.
        """
        if not BACKUP_CHAT_ID:
            logger.info("BACKUP_CHAT_ID not configured. Skipping persistent database restore.")
            return False

        if not self.bot:
            logger.error("BackupManager bot instance is not set. Cannot restore backup.")
            return False

        try:
            logger.info(f"Checking for persistent database backup in chat/channel: {BACKUP_CHAT_ID}...")
            
            # Fetch chat info to get the latest pinned message
            chat = await self.bot.get_chat(BACKUP_CHAT_ID)
            pinned = chat.pinned_message
            
            if not pinned or not pinned.document:
                logger.info("No pinned database backup document found in backup chat/channel.")
                return False

            doc = pinned.document
            if not doc.file_name or not doc.file_name.endswith(".db"):
                logger.warning(f"Pinned document '{doc.file_name}' is not a SQLite database file. Skipping restore.")
                return False

            logger.info(f"Found pinned database backup '{doc.file_name}' (size: {doc.file_size} bytes). Downloading...")
            
            # Ensure the database directory exists
            os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)
            
            # Download file to path
            file = await self.bot.get_file(doc.file_id)
            await file.download_to_drive(DATABASE_PATH)
            
            logger.info("Database successfully restored from Telegram backup!")
            
            # Sync our last backup time to the newly downloaded file modification time
            if os.path.exists(DATABASE_PATH):
                self.last_backup_mtime = os.path.getmtime(DATABASE_PATH)
            return True
            
        except Exception as e:
            logger.error(f"Failed to restore database backup from Telegram: {e}", exc_info=True)
            return False

    async def perform_backup(self) -> bool:
        """
        Checks if the database has been modified since the last backup.
        If yes, uploads it to the backup channel and pins it.
        """
        if not BACKUP_CHAT_ID:
            return False

        if not self.bot:
            return False

        if not os.path.exists(DATABASE_PATH):
            return False

        try:
            current_mtime = os.path.getmtime(DATABASE_PATH)
            
            # Only backup if the file has been modified since the last backup operation
            if current_mtime <= self.last_backup_mtime:
                return False

            # Add a small delay to ensure SQLite has finished writing and released locks
            await asyncio.sleep(1.0)
            
            logger.info(f"Database modification detected. Uploading backup to chat/channel: {BACKUP_CHAT_ID}...")
            
            # Send file to backup channel
            with open(DATABASE_PATH, "rb") as db_file:
                msg = await self.bot.send_document(
                    chat_id=BACKUP_CHAT_ID,
                    document=db_file,
                    filename=os.path.basename(DATABASE_PATH),
                    caption=f"📂 <b>Bot Database Backup</b>\n\n• Timestamp: <code>{time.strftime('%Y-%m-%d %H:%M:%S')}</code>",
                    parse_mode="HTML"
                )
            
            # Pin the new backup message silently
            await self.bot.pin_chat_message(
                chat_id=BACKUP_CHAT_ID,
                message_id=msg.message_id,
                disable_notification=True
            )
            
            self.last_backup_mtime = current_mtime
            logger.info("Database backup successfully uploaded and pinned.")
            return True
            
        except Exception as e:
            logger.error(f"Failed to perform database backup to Telegram: {e}", exc_info=True)
            return False

    async def start_backup_loop(self, interval_seconds: int = 120):
        """Background loop that periodically checks for changes and triggers backups."""
        if not BACKUP_CHAT_ID:
            logger.warning("BACKUP_CHAT_ID is empty. Telegram persistent backups are DISABLED.")
            return

        logger.info(f"Telegram persistent backup loop started (checking every {interval_seconds}s)...")
        while True:
            await asyncio.sleep(interval_seconds)
            await self.perform_backup()

# Singleton instance
backup_manager = BackupManager()
