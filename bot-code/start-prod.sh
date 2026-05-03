#!/bin/bash
set -e

echo "Starting Telegram OTP Bot..."
python telegram-bot/main.py &
BOT_PID=$!

echo "Starting API health server..."
node --enable-source-maps artifacts/api-server/dist/index.mjs &
API_PID=$!

echo "Both services running. Bot PID=$BOT_PID, API PID=$API_PID"

# If either process exits, kill the other and exit
wait -n $BOT_PID $API_PID
EXIT_CODE=$?

echo "A process exited. Shutting down..."
kill $BOT_PID $API_PID 2>/dev/null
exit $EXIT_CODE
