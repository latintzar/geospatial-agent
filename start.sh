#!/bin/bash
# =============================================================================
# Leo - Start Both Backend and Frontend
# =============================================================================
# Run this from the Leo directory: ./start.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "🦁 Starting Leo..."
echo "   Directory: $SCRIPT_DIR"

# Load environment variables from Leo directory
if [ -f ".env.local" ]; then
    export $(grep -v '^#' .env.local | xargs 2>/dev/null)
    echo "   ✅ Loaded .env.local"
else
    echo "   ⚠️  No .env.local found! Copy env.template to .env.local and add your API keys"
fi

if [ -f ".env" ]; then
    export $(grep -v '^#' .env | xargs 2>/dev/null)
    echo "   Loaded .env"
fi

# Check for required environment variables
if [ -z "$GOOGLE_AI_API_KEY" ] && [ -z "$GEMINI_API_KEY_HELLO" ]; then
    echo "⚠️  Warning: No Gemini API key found. Set GOOGLE_AI_API_KEY or GEMINI_API_KEY_HELLO"
fi

# Start backend (run from Leo directory so imports work)
echo ""
echo "🚀 Starting Backend (port 8000)..."
python -m uvicorn backend.main:app --reload --port 8000 &
BACKEND_PID=$!

# Wait for backend to be ready
echo "   Waiting for backend..."
sleep 3
if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "   ✅ Backend ready"
else
    echo "   ⚠️  Backend may still be starting..."
fi

# Start frontend
echo ""
echo "🚀 Starting Frontend (port 3000)..."
cd frontend
npm run dev &
FRONTEND_PID=$!
cd ..

# Wait for frontend
sleep 5

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                    🦁 LEO IS READY                           ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║  Frontend:  http://localhost:3000                            ║"
echo "║  Backend:   http://localhost:8000                            ║"
echo "║  API Docs:  http://localhost:8000/docs                       ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "Press Ctrl+C to stop all services..."

# Wait for both processes
wait $BACKEND_PID $FRONTEND_PID
