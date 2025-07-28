#!/bin/bash

# Simple script to run the Langroid Chat UI

echo "🚀 Starting Langroid Chat UI..."
echo ""

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

# Function to check if port is in use
check_port() {
    local port=$1
    local service=$2
    
    if lsof -i :$port > /dev/null 2>&1; then
        echo -e "${RED}❌ Error: Port $port is already in use!${NC}"
        echo ""
        echo "The following process is using port $port:"
        lsof -i :$port | grep LISTEN
        echo ""
        echo -e "${YELLOW}To fix this, you can:${NC}"
        echo "1. Kill the process using: kill -9 <PID>"
        echo "2. Or find and kill all processes on port $port:"
        echo "   lsof -ti :$port | xargs kill -9"
        echo ""
        return 1
    fi
    return 0
}

# Check ports before starting
echo "Checking port availability..."
PORT_CHECK_FAILED=false

if ! check_port 8000 "Backend (FastAPI)"; then
    PORT_CHECK_FAILED=true
fi

if ! check_port 5173 "Frontend (Vite)"; then
    PORT_CHECK_FAILED=true
fi

if [ "$PORT_CHECK_FAILED" = true ]; then
    echo -e "${RED}Cannot start servers due to port conflicts.${NC}"
    echo "Please resolve the conflicts and try again."
    exit 1
fi

echo -e "${GREEN}✅ Ports are available!${NC}"
echo ""

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

# Check if backend started successfully
if ! curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo -e "${RED}❌ Backend failed to start!${NC}"
    echo "Check the logs above for error messages."
    kill $BACKEND_PID 2>/dev/null
    exit 1
fi

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
echo "📡 Backend health check: http://localhost:8000/health"
echo "📡 Backend API docs: http://localhost:8000/docs"
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