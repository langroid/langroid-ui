#!/bin/bash

# Start the Langroid Chat UI locally

echo "Starting Langroid Chat UI..."

# Function to cleanup on exit
cleanup() {
    echo "Shutting down servers..."
    pkill -f "python.*main.py" || true
    pkill -f "vite" || true
    exit 0
}

# Set trap for cleanup
trap cleanup EXIT INT TERM

# Start backend
echo "Starting backend on http://localhost:8000..."
cd backend
python main.py &
BACKEND_PID=$!

# Wait for backend to start
sleep 3

# Start frontend
echo "Starting frontend on http://localhost:5173..."
cd ../frontend
npm run dev &
FRONTEND_PID=$!

# Wait for frontend to start
sleep 3

echo ""
echo "🚀 Langroid Chat UI is running!"
echo "📍 Frontend: http://localhost:5173"
echo "📍 Backend: http://localhost:8000"
echo ""
echo "Press Ctrl+C to stop the servers"

# Wait for processes
wait $BACKEND_PID $FRONTEND_PID