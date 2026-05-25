import os
import time
import asyncio
import urllib.request
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from config import logger

class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ('/', '/ping'):
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status": "alive", "message": "Antigravity Bot is active!"}')
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
