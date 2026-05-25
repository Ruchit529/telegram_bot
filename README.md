# Enterprise-Grade Telegram Translation & Posting Bot

A production-ready, highly modular, fault-tolerant, and async-safe Telegram bot designed to ingest posts (text, photos, or videos) in any language, automatically translate them to English, and facilitate scheduled and batch queue channel distribution.

---

## 🚀 Key Features

*   **Language Auto-Detection & Translation:** Non-blocking async translation offloaded to a thread pool utilizing `deep-translator` and `langdetect`.
*   **Dynamic Preview System:** Edit draft posts, toggle footers, and preview custom inline keyboard layouts in-place without cluttering chat history.
*   **Persistent SQLite-backed State Management (FSM):** Complete user state isolation with read-through-to-DB mapping, ensuring safety against system crashes or mid-workflow restarts.
*   **Asynchronous Rate-Limited Queue Manager:** Guarantees strict adherence to Telegram's flood rules (max 1 message/sec per channel, 30 messages/sec globally) while batching sends with exponential backoff retries.
*   **Centralized Crash Protection:** Complete exception wrappers, Callback Debouncing to block spam clicks, and automated sweeper threads to clean abandoned memory allocations.

---

## 📂 Architecture & Directory Layout

```text
f:\bot\
│   .env.example          # Environment variables template
│   config.py             # Centralized settings and logger
│   database.py           # aiosqlite asynchronous persistence interface
│   Dockerfile            # Multi-stage production container setup
│   main.py               # Application entrypoint & handler configurations
│   requirements.txt      # Dependency manifest
│   README.md             # System documentation
│
├───handlers/
│   │   __init__.py
│   │   admin.py          # Admin panel commands, channel & footer config
│   │   error_handler.py  # Global error traps & safe edit/delete wrappers
│   │   post_workflow.py  # Ingestion workflow, translation, and previews
│   
└───services/
    │   __init__.py
    │   fsm.py            # isolated Finite State Machine with active locks
    │   queue_manager.py  # Non-blocking backoff posting queue worker
    │   translation.py    # Auto-detection tokenized translation service
```

---

## 🛠 Stability Matrix & Edge Case Resolvers

This bot is engineered to **NEVER crash** under any production scenario. Here is how specific edge cases are mitigated:

| Scenario / Edge Case | Mitigation Engineering |
| :--- | :--- |
| **Spamming Buttons / Cancel** | Callback debouncing discards actions closer than `0.5s` apart. Active Locks per User ID (`asyncio.Lock`) inside the FSM guarantee thread safety. |
| **Simultaneous Admin Action** | FSM states are key-isolated by Telegram User ID. State files sync immediately to SQLite, permitting multiple admins to schedule content concurrently. |
| **Restarting mid-workflow** | Active drafts, queue items, and channel footers are saved persistently to SQLite. Upon boot, active states are resumed without loss of data. |
| **Deleted Preview Messages** | Previews are updated using `safe_edit_message_text/caption` wrappers. If the message is deleted, it catches `BadRequest` gracefully and sends a brand new message, recording the new ID. |
| **Stale inline buttons** | Old callback queries from expired workflow panels check active FSM versioning; invalid queries trigger a "This menu has expired" alert, avoiding orphaned states. |
| **Telegram Rate Limits (429)** | The Queue Manager intercepts `RetryAfter` exceptions, pauses operations for the exact timeout duration, and schedules automatic retries. |
| **Unsupported Media Format** | Incoming posts are filtered by a strict media validator. If unsupported, the admin receives a safe warning message. |

---

## 🚀 Setup & Execution Guide

### Local Execution (using the pre-created virtual environment)

1.  **Clone the workspace** and navigate to the bot root.
2.  **Configure environment variables:**
    Copy `.env.example` to `.env` and fill in your values:
    ```bash
    cp .env.example .env
    ```
    *Provide your `BOT_TOKEN` (from [@BotFather](https://t.me/BotFather)) and your `ADMIN_IDS` (comma-separated list of Telegram User IDs).*

3.  **Activate Virtual Environment & Install Dependencies:**
    *On Windows:*
    ```powershell
    .\venv\Scripts\activate
    pip install -r requirements.txt
    ```
4.  **Run the application:**
    ```bash
    python main.py
    ```

### Production Deployment via Docker

Compile, build, and execute in a containerized sandbox with a local data directory mapped for database persistence:

```bash
# Build the Docker image
docker build -t telegram-translation-bot .

# Execute the container with persistent volume mounts
docker run -d \
  --name tg-bot \
  -v $(pwd)/data:/app/data \
  --env-file .env \
  --restart unless-stopped \
  telegram-translation-bot
```

---

## 📋 Interactive Formatting Syntax (Buttons)

When editing inline buttons in the preview control board, submit your custom keyboards using the following format:
```text
Google -> https://google.com | GitHub -> https://github.com
Support Chat -> t.me/support
```
*   Use `->` to link titles with destinations.
*   Use `|` to separate buttons on the *same row*.
*   Use newlines to establish *separate rows*.
