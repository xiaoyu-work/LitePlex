#!/bin/bash

echo "Starting LitePlex..."
echo "===================="

# Function to kill process on port
kill_port() {
    port=$1
    echo "Checking port $port..."
    lsof -i :$port | grep LISTEN | awk '{print $2}' | xargs -r kill -9 2>/dev/null
}

# Clean up ports
kill_port 8088
kill_port 3000

# Start backend
echo ""
echo "Starting backend API server on port 8088..."
python web_app.py &
BACKEND_PID=$!

# Wait for backend to start
sleep 2

# Start frontend
echo ""
echo "Starting frontend on port 3000..."
cd frontend
npm install --silent 2>/dev/null
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
    kill_port 8088
    kill_port 3000
    echo "Services stopped."
    exit 0
}

# Set up trap for Ctrl+C
trap cleanup INT

# Wait for both processes
wait $BACKEND_PID $FRONTEND_PID