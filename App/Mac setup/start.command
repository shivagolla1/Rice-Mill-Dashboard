#!/bin/bash
cd "$(dirname "$0")"

echo ""
echo " ============================================"
echo "  SGRI Dashboard - Starting Server (macOS)"
echo " ============================================"
echo ""

# 1. Kill existing process on port 5000
echo " [1/3] Checking for existing server on port 5000..."
EXISTING_PID=$(lsof -t -i:5000)
if [ -n "$EXISTING_PID" ]; then
    echo "       Stopping existing server (PID $EXISTING_PID)..."
    kill -9 $EXISTING_PID
else
    echo "       No existing server found. Continuing..."
fi

# 2. Check for python3
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: python3 is not installed on this system."
    echo "   Please download and install Python from https://www.python.org/downloads/"
    exit 1
fi

# 3. Install dependencies if requirements.txt exists
if [ -f "requirements.txt" ]; then
    echo "       Checking and installing dependencies..."
    pip3 install -r requirements.txt > /dev/null 2>&1
fi

# 4. Start Flask server
echo " [2/3] Starting Flask server..."
export PYTHONUTF8=1
python3 app.py > server.log 2>&1 &
SERVER_PID=$!

# 5. Wait for warmup
echo "       Waiting for server to start and database to load (8 seconds)..."
sleep 8

# 6. Open in default browser
# echo " [3/3] Opening in default browser..."
# open "http://localhost:5000"

echo ""
echo " ============================================"
echo "  Server is running!"
echo "  URL : http://localhost:5000"
echo "  Stop: double-click stop.command"
echo "  Log : check server.log for logs"
echo " ============================================"
echo ""
echo " Press enter to close this window..."
read -r
