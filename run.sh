#!/bin/bash

# Simple script to run the Langroid Chat UI

echo "🚀 Starting Langroid Chat UI..."
echo ""

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Kill any existing processes
echo "Cleaning up any existing processes..."
pkill -f "python.*main.py" || true
pkill -f "vite" || true
sleep 2

# Start backend
echo -e "${BLUE}Starting backend server...${NC}"
cd backend

# Check if UV is available and use it if present
if command -v uv &> /dev/null; then
    echo "Using UV to run backend..."
    uv run python main.py &
else
    echo "UV not found, using Python directly..."
    python main.py &
fi

BACKEND_PID=$!
echo "Backend PID: $BACKEND_PID"

# Wait for backend to start
echo "Waiting for backend to start..."
sleep 3

# Start frontend
echo -e "${BLUE}Starting frontend server...${NC}"
cd ../frontend
npm run dev &
FRONTEND_PID=$!
echo "Frontend PID: $FRONTEND_PID"

# Wait for frontend to start
sleep 3

echo ""
echo -e "${GREEN}✅ Langroid Chat UI is running!${NC}"
echo ""
echo "📍 Open your browser to: http://localhost:5173"
echo "📡 Backend API running on: http://localhost:8000"
echo ""
echo "Press Ctrl+C to stop both servers"
echo ""

# Function to cleanup on exit
cleanup() {
    echo ""
    echo "Shutting down servers..."
    kill $BACKEND_PID 2>/dev/null
    kill $FRONTEND_PID 2>/dev/null
    pkill -f "python.*main.py" || true
    pkill -f "vite" || true
    echo "Goodbye! 👋"
    exit 0
}

# Set trap to cleanup on Ctrl+C
trap cleanup INT TERM

# Wait forever
while true; do
    sleep 1
done