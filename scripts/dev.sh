#!/usr/bin/env bash
set -e

cd "$(dirname "$0")/.."

mkdir -p logs

# Start backend (logs to file + stdout)
echo "Starting backend on :8000..."
uvicorn backend.main:app --reload --app-dir src --port 8000 \
  > logs/backend-stdout.log 2>&1 &
BACKEND_PID=$!

# Wait for backend to be ready
echo "Waiting for backend..."
for i in $(seq 1 30); do
  if curl -sf http://localhost:8000/api/templates > /dev/null 2>&1; then
    echo "Backend ready."
    break
  fi
  sleep 1
done

# Start frontend
echo "Starting frontend on :5173..."
cd src/frontend && npm run dev > ../../logs/frontend.log 2>&1 &
FRONTEND_PID=$!
cd ../..

echo ""
echo "=== Dev servers running ==="
echo "Backend:  http://localhost:8000  (PID $BACKEND_PID)"
echo "Frontend: http://localhost:5173  (PID $FRONTEND_PID)"
echo ""
echo "Logs:"
echo "  tail -f logs/backend.log         # app logs"
echo "  tail -f logs/backend-stdout.log  # uvicorn access logs"
echo "  tail -f logs/frontend.log        # vite logs"
echo ""
echo "Press Ctrl+C to stop both servers."

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; echo 'Servers stopped.'" EXIT
wait
