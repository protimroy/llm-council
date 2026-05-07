#!/bin/bash

# LLM Council - Start script

echo "Starting LLM Council..."
echo ""

if [ -f .env ]; then
	set -a
	. ./.env
	set +a
fi

BACKEND_URL="http://${BACKEND_HOST:-localhost}:${BACKEND_PORT:-8001}"
FRONTEND_HOST_VALUE="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT_VALUE="${FRONTEND_PORT:-5173}"
FRONTEND_URL="http://localhost:${FRONTEND_PORT_VALUE}"

# Start backend
echo "Starting backend on ${BACKEND_URL}..."
uv run python -m backend.main &
BACKEND_PID=$!

# Wait a bit for backend to start
sleep 2

# Start frontend
echo "Starting frontend on ${FRONTEND_URL}..."
cd frontend
npm run dev -- --host "${FRONTEND_HOST_VALUE}" --port "${FRONTEND_PORT_VALUE}" &
FRONTEND_PID=$!

echo ""
echo "✓ LLM Council is running!"
echo "  Backend:  ${BACKEND_URL}"
echo "  Frontend: ${FRONTEND_URL}"
echo ""
echo "Press Ctrl+C to stop both servers"

# Wait for Ctrl+C
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" SIGINT SIGTERM
wait
