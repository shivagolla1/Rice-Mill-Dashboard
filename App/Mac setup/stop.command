#!/bin/bash
cd "$(dirname "$0")"

echo ""
echo " ============================================"
echo "  SGRI Dashboard - Stopping Server (macOS)"
echo " ============================================"
echo ""

EXISTING_PID=$(lsof -t -i:5000)
if [ -n "$EXISTING_PID" ]; then
    echo "Stopping server on PID $EXISTING_PID..."
    kill -9 $EXISTING_PID
    echo "✓ Server stopped successfully."
else
    echo "No server running on port 5000."
fi
sleep 3
