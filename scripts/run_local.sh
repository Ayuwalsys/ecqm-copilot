#!/bin/bash
# Run backend + frontend locally in parallel

echo "Installing backend deps..."
cd backend && pip install -r requirements.txt -q

echo "Installing frontend deps..."
cd ../frontend && pip install -r requirements.txt -q

echo ""
echo "Starting backend on :8000 and frontend on :8501..."
echo ""

cd ../backend && uvicorn main:app --reload --port 8000 &
BACKEND_PID=$!

cd ../frontend && BACKEND_URL=http://localhost:8000 streamlit run app.py --server.port 8501 &
FRONTEND_PID=$!

echo "Backend PID: $BACKEND_PID"
echo "Frontend PID: $FRONTEND_PID"
echo ""
echo "Open http://localhost:8501"
echo "Press Ctrl+C to stop both."

wait
