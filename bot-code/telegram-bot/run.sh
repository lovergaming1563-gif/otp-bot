#!/bin/bash
set -e
cd "$(dirname "$0")"

echo "=== OTP Bot Starting ==="
echo "Python: $(python3 --version)"
echo "Working dir: $(pwd)"

# Kill any leftover processes from previous runs
pkill -f "python main.py"    2>/dev/null || true
pkill -f "python userbot.py" 2>/dev/null || true
sleep 1

# Kill all child processes on exit (graceful shutdown)
cleanup() {
    echo "Shutting down all processes..."
    kill 0 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Health-check HTTP server on $PORT (required for Railway, Render & Replit)
PORT="${PORT:-8080}"

python3 -c "
import os
from http.server import HTTPServer, BaseHTTPRequestHandler

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'OK - OTP Bot is running')
    def do_HEAD(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
    def log_message(self, *a): pass

port = int(os.environ.get('PORT', 8080))
print(f'Health server running on port {port}', flush=True)
HTTPServer(('0.0.0.0', port), H).serve_forever()
" &

HEALTH_PID=$!
echo "Health server PID: $HEALTH_PID"

# Internal self-ping every 4 minutes to prevent Render free tier sleep
python3 -c "
import time, urllib.request, os

port = int(os.environ.get('PORT', 8080))
url  = f'http://localhost:{port}/'

print('Self-ping loop started (every 4 min)', flush=True)
while True:
    time.sleep(240)
    try:
        urllib.request.urlopen(url, timeout=10)
        print('Self-ping OK', flush=True)
    except Exception as e:
        print(f'Self-ping failed: {e}', flush=True)
" &

PING_PID=$!
echo "Self-ping PID: $PING_PID"

# Start Pyrogram userbot (only if credentials provided)
if [ -n "$SESSION_STRING" ] && [ -n "$API_ID" ] && [ -n "$API_HASH" ]; then
    echo "Starting userbot (Pyrogram)..."
    python3 userbot.py &
else
    echo "Userbot disabled — SESSION_STRING / API_ID / API_HASH not set"
fi

# Start main Telegram bot
echo "Starting main bot..."
exec python3 main.py
