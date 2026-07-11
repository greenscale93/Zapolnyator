#!/bin/bash
set -e

export LD_LIBRARY_PATH="/usr/lib/libreoffice/program:${LD_LIBRARY_PATH}"
export PYTHONPATH="/usr/lib/libreoffice/program:${PYTHONPATH}"

echo "Starting LibreOffice in background..."
soffice --headless --norestore \
    --accept="socket,host=localhost,port=2002;urp;" &

echo "Waiting for LibreOffice to initialize..."
sleep 5

echo "Starting uvicorn..."
exec uvicorn src.main:app --host 0.0.0.0 --port 8000
