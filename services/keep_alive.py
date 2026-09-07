import os
import time
import asyncio
import urllib.request
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from config import logger

_main_event_loop = None
_global_bot = None

def register_main_loop_and_bot(bot, loop):
    global _global_bot, _main_event_loop
    _global_bot = bot
    _main_event_loop = loop
    logger.info("Bot instance and main asyncio loop registered to keep_alive server.")

WEB_EDITOR_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Edit Caption</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <style>
        :root {
            --bg-color: var(--tg-theme-bg-color, #18222d);
            --text-color: var(--tg-theme-text-color, #ffffff);
            --hint-color: var(--tg-theme-hint-color, #708499);
            --button-color: var(--tg-theme-button-color, #2b5278);
            --button-text-color: var(--tg-theme-button-text-color, #ffffff);
            --secondary-bg: var(--tg-theme-secondary-bg-color, #212d3b);
        }
        body {
            background-color: var(--bg-color);
            color: var(--text-color);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            margin: 0;
            padding: 16px;
            box-sizing: border-box;
            display: flex;
            flex-direction: column;
            height: 100vh;
        }
        h3 {
            margin-top: 0;
            margin-bottom: 8px;
            font-size: 18px;
            font-weight: 600;
        }
        .instructions {
            font-size: 13px;
            color: var(--hint-color);
            margin-bottom: 12px;
        }
        textarea {
            width: 100%;
            flex: 1;
            background-color: var(--secondary-bg);
            color: var(--text-color);
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 12px;
            padding: 14px;
            font-size: 15px;
            font-family: inherit;
            resize: none;
            box-sizing: border-box;
            outline: none;
            line-height: 1.45;
        }
        textarea:focus {
            border-color: var(--button-color);
        }
        .btn-container {
            display: flex;
            gap: 10px;
            margin-top: 14px;
        }
        button {
            flex: 1;
            padding: 14px;
            border: none;
            border-radius: 12px;
            font-size: 15px;
            font-weight: 600;
            cursor: pointer;
            transition: opacity 0.2s;
        }
        button:active {
            opacity: 0.8;
        }
        .btn-save {
            background-color: var(--button-color);
            color: var(--button-text-color);
        }
        .btn-cancel {
            background-color: transparent;
            color: var(--hint-color);
            border: 1px solid var(--hint-color);
        }
    </style>
</head>
<body>
    <h3>✏️ Edit Post Caption</h3>
    <div class="instructions">Edit your caption below and tap <b>Save & Apply</b> to update your preview.</div>
    <textarea id="caption-input" placeholder="Type or edit your caption here..."></textarea>
    <div class="btn-container">
        <button class="btn-cancel" id="cancel-btn">Cancel</button>
        <button class="btn-save" id="save-btn">💾 Save & Apply</button>
    </div>

    <script>
        const tg = window.Telegram.WebApp;
        tg.expand();
        tg.ready();

        const urlParams = new URLSearchParams(window.location.search);
        const textParam = urlParams.get('text');
        if (textParam !== null) {
            document.getElementById('caption-input').value = decodeURIComponent(textParam);
        }

        document.getElementById('save-btn').onclick = function() {
            const updatedText = document.getElementById('caption-input').value;
            const userId = tg.initDataUnsafe?.user?.id || urlParams.get('user_id');

            const saveBtn = document.getElementById('save-btn');
            saveBtn.innerText = "⏳ Saving...";
            saveBtn.disabled = true;

            fetch('/api/save_caption', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_id: parseInt(userId), text: updatedText })
            })
            .then(res => res.json())
            .then(data => {
                try { tg.sendData(JSON.stringify({ action: "update_caption", text: updatedText })); } catch(e) {}
                tg.close();
            })
            .catch(err => {
                try { tg.sendData(JSON.stringify({ action: "update_caption", text: updatedText })); } catch(e) {}
                tg.close();
            });
        };

        document.getElementById('cancel-btn').onclick = function() {
            tg.close();
        };
    </script>
</body>
</html>
"""

async def _apply_caption_update(user_id: int, text: str):
    """Bridge routine to update FSM draft state and edit preview message on main asyncio loop."""
    try:
        from services.fsm import fsm, States
        from handlers.post_workflow import _update_existing_preview
        from handlers.error_handler import safe_delete_message

        state, draft = await fsm.get_state(user_id)
        if draft:
            guide_id = draft.get("caption_guide_msg_id")
            if guide_id and _global_bot:
                await safe_delete_message(_global_bot, user_id, guide_id)
                if "caption_guide_msg_id" in draft:
                    del draft["caption_guide_msg_id"]

            draft["translated_text"] = text
            draft["was_translated"] = False

            await fsm.set_state(user_id, States.PREVIEW_GENERATED, draft)
            if _global_bot:
                await _update_existing_preview(_global_bot, user_id, draft)
    except Exception as e:
        logger.error(f"Error applying caption update: {e}", exc_info=True)

class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ('/', '/ping'):
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status": "alive", "message": "Antigravity Bot is active!"}')
        elif self.path.startswith('/editor') or self.path.startswith('/webapp'):
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(WEB_EDITOR_HTML.encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == '/api/save_caption':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            try:
                import json
                data = json.loads(post_data.decode('utf-8'))
                user_id = data.get("user_id")
                text = data.get("text", "")
                
                if user_id and _main_event_loop and _main_event_loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        _apply_caption_update(int(user_id), text),
                        _main_event_loop
                    )

                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"status": "ok"}')
            except Exception as e:
                logger.error(f"Error in /api/save_caption POST: {e}", exc_info=True)
                self.send_response(500)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    # Suppress standard request logging to avoid log pollution
    def log_message(self, format, *args):
        logger.debug(format % args)

def run_http_server(port: int):
    try:
        server = HTTPServer(('0.0.0.0', port), KeepAliveHandler)
        logger.info(f"Keep-alive HTTP server listening on 0.0.0.0:{port}")
        server.serve_forever()
    except Exception as e:
        logger.error(f"Failed to start keep-alive HTTP server: {e}", exc_info=True)

async def self_ping_loop():
    # Render automatically populates RENDER_EXTERNAL_URL (e.g., https://bot-service.onrender.com)
    ping_url = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("PING_URL")
    if not ping_url:
        logger.warning("Neither RENDER_EXTERNAL_URL nor PING_URL is set in environment. Self-pinging is disabled.")
        return

    if not ping_url.startswith(("http://", "https://")):
        ping_url = "https://" + ping_url
    
    ping_url = ping_url.rstrip("/") + "/ping"
    logger.info(f"Self-pinging keep-alive loop initialized. Target URL: {ping_url}")

    # Wait 60 seconds after startup before sending the first self-ping
    await asyncio.sleep(60)

    while True:
        try:
            def ping():
                try:
                    req = urllib.request.Request(
                        ping_url,
                        headers={'User-Agent': 'Antigravity-Keep-Alive/1.0'}
                    )
                    with urllib.request.urlopen(req, timeout=15) as response:
                        return response.read().decode('utf-8')
                except Exception as ex:
                    return f"HTTP Request Error: {str(ex)}"

            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, ping)
            logger.info(f"Keep-alive ping sent successfully. Response: {result}")
        except Exception as e:
            logger.error(f"Keep-alive self-ping failed: {e}")

        # Ping every 10 minutes (600 seconds) to prevent Render's 15-minute sleep timeout
        await asyncio.sleep(600)

def start_keep_alive():
    """Starts the port listener and schedules the self-ping loop."""
    port_str = os.getenv("PORT", "10000")
    try:
        port = int(port_str)
    except ValueError:
        logger.warning(f"Invalid PORT value: '{port_str}'. Defaulting to 10000.")
        port = 10000

    # Run the HTTP server in a separate background daemon thread to avoid blocking the asyncio event loop
    threading.Thread(target=run_http_server, args=(port,), daemon=True).start()

    # Schedule the self-ping loop on the running asyncio event loop
    asyncio.create_task(self_ping_loop())
