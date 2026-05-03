#!/bin/bash
set -e

echo "=== OTP Bot Service Starting ==="

# Start the Telegram bot in background
echo "[1/2] Starting Telegram OTP Bot..."
cd /home/runner/workspace
python telegram-bot/main.py &
BOT_PID=$!

# Serve the static React site on PORT for health checks
echo "[2/2] Starting static file server on port $PORT..."
python3 -c "
import http.server, os, sys
from http.server import HTTPServer, SimpleHTTPRequestHandler

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory='artifacts/bot-status/dist/public', **kwargs)
    def do_GET(self):
        # SPA fallback
        path = self.translate_path(self.path)
        if not os.path.exists(path) or os.path.isdir(path):
            self.path = '/index.html'
        return super().do_GET()
    def log_message(self, format, *args):
        pass  # suppress request logs

port = int(os.environ.get('PORT', 8080))
server = HTTPServer(('0.0.0.0', port), Handler)
print(f'Static server running on port {port}', flush=True)
server.serve_forever()
" &
SERVER_PID=$!

echo "Bot PID=$BOT_PID | Server PID=$SERVER_PID"

# Exit when either process exits
wait -n $BOT_PID $SERVER_PID
EXIT_CODE=$?
echo "A process exited with code $EXIT_CODE. Shutting down..."
kill $BOT_PID $SERVER_PID 2>/dev/null
exit $EXIT_CODE
