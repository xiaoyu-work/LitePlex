#!/bin/bash

echo "Starting LitePlex..."
echo "===================="

if ! command -v uv >/dev/null 2>&1; then
    echo "Error: uv is required. Install it from https://docs.astral.sh/uv/"
    exit 1
fi

# Start backend
echo ""
echo "Starting backend API server on port 8088..."
uv run --python 3.10 --with-requirements requirements.txt python web_app.py &
BACKEND_PID=$!

# Wait for backend to start
sleep 2

# Start frontend
echo ""
echo "Starting frontend on port 3000..."
cd frontend
if [ ! -d "node_modules" ]; then
    npm ci
fi
npm run dev &
FRONTEND_PID=$!

echo ""
echo "================================"
echo "LitePlex is running!"
echo "================================"
echo "🌐 Frontend: http://localhost:3000"
echo "🔧 Backend API: http://localhost:8088"
echo ""
echo "Press Ctrl+C to stop both services"
echo ""

# Function to cleanup on exit
cleanup() {
    echo ""
    echo "Stopping services..."
    kill $BACKEND_PID 2>/dev/null
    kill $FRONTEND_PID 2>/dev/null
    echo "Services stopped."
    exit 0
}

# Set up trap for Ctrl+C
trap cleanup INT

# Wait for both processes
wait $BACKEND_PID $FRONTEND_PID
