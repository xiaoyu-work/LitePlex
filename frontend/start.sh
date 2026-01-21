#!/bin/bash

echo "Starting LitePlex Frontend..."
echo "================================"

# Install dependencies if needed
if [ ! -d "node_modules" ]; then
    echo "Installing dependencies..."
    npm install
fi

# Start the development server
echo "Starting Next.js development server on http://localhost:3000"
npm run dev