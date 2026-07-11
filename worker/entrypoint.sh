#!/bin/bash
set -e

echo "Starting LibreOffice in background..."
soffice --headless --norestore \
    --accept="socket,host=localhost,port=2002;urp;" &

# Wait for LibreOffice socket
echo "Waiting for LibreOffice to initialize..."
sleep 5

echo "Starting uvicorn..."
exec uvicorn src.main:app --host 0.0.0.0 --port 8000
