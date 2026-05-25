import asyncio
import time
from typing import Dict, Tuple, Any, Optional
from config import logger, STATE_EXPIRY_SECONDS, PREVIEW_EXPIRY_SECONDS
from database import db

# Define States
class States:
    NONE = "NONE"
    AWAITING_POST = "AWAITING_POST"
    PREVIEW_GENERATED = "PREVIEW_GENERATED"
    EDITING_FOOTER = "EDITING_FOOTER"
    EDITING_BUTTONS = "EDITING_BUTTONS"
    EDITING_CAPTION = "EDITING_CAPTION"
    AWAITING_SCHEDULE_TIME = "AWAITING_SCHEDULE_TIME"
    POSTING = "POSTING"

class StateManager:
    def __init__(self):
        # Memory cache for FSM state/data for instantaneous lookups
        # Format: {user_id: (state, data_dict, last_activity_timestamp)}
        self._cache: Dict[int, Tuple[str, Dict[str, Any], float]] = {}
        # Concurrency locks per user to block duplicate actions or race conditions
        self._locks: Dict[int, asyncio.Lock] = {}
        self._lock_creation_lock = asyncio.Lock()

    async def get_lock(self, user_id: int) -> asyncio.Lock:
        """Retrieves a thread-safe / async-safe lock for a specific user to prevent concurrent overlap."""
        async with self._lock_creation_lock:
            if user_id not in self._locks:
                self._locks[user_id] = asyncio.Lock()
            return self._locks[user_id]

    async def get_state(self, user_id: int) -> Tuple[str, Dict[str, Any]]:
        """Gets state and data for a user, checking memory first, falling back to SQLite."""
        async with await self.get_lock(user_id):
            # Check memory cache
            if user_id in self._cache:
                state, data, _ = self._cache[user_id]
                # Update last active timestamp
                self._cache[user_id] = (state, data, time.time())
                return state, data

            # Fallback to Database
            db_state, db_data, _ = await db.get_state(user_id)
            if db_state:
                self._cache[user_id] = (db_state, db_data, time.time())
                return db_state, db_data

            # Default if no state exists
            return States.NONE, {}

    async def set_state(self, user_id: int, state: str, data: Dict[str, Any]):
        """Sets state and data both in-memory and persistently in the database."""
        async with await self.get_lock(user_id):
            now = time.time()
            self._cache[user_id] = (state, data, now)
            # Sync to Database
            await db.set_state(user_id, state, data)
            logger.debug(f"User {user_id} transitioned to state: {state}")

    async def clear_state(self, user_id: int):
        """Clears state both in-memory and persistently in the database."""
        async with await self.get_lock(user_id):
            if user_id in self._cache:
                del self._cache[user_id]
            # Sync to Database
            await db.clear_state(user_id)
            logger.debug(f"User {user_id} state cleared.")

    async def cleanup_abandoned_states(self):
        """Sweeps abandoned FSM states and previews. Triggered by a background loop."""
        try:
            logger.info("Running FSM background state cleanup...")
            now = time.time()
            expired_users = []

            # 1. Clean Memory Cache
            for user_id, (state, data, last_active) in list(self._cache.items()):
                if now - last_active > STATE_EXPIRY_SECONDS:
                    expired_users.append(user_id)

            for user_id in expired_users:
                async with await self.get_lock(user_id):
                    # Ensure it's still expired inside lock
                    if user_id in self._cache and now - self._cache[user_id][2] > STATE_EXPIRY_SECONDS:
                        del self._cache[user_id]
                        logger.info(f"Cleaned up inactive in-memory state for user {user_id}")

            # 2. Clean Database expired entries
            await db.cleanup_expired_states(STATE_EXPIRY_SECONDS)

            # 3. Clean up stale locks to prevent memory leakage
            async with self._lock_creation_lock:
                for user_id in list(self._locks.keys()):
                    if user_id not in self._cache:
                        # Only delete lock if it's currently unlocked
                        lock = self._locks[user_id]
                        if not lock.locked():
                            del self._locks[user_id]

        except Exception as e:
            logger.error(f"Error during FSM state cleanup: {e}", exc_info=True)

    async def start_cleanup_loop(self, interval_seconds: int = 300):
        """Background task that runs continuously to clean up expired states."""
        while True:
            await asyncio.sleep(interval_seconds)
            await self.cleanup_abandoned_states()

# Singleton FSM Manager
fsm = StateManager()
