#!/bin/bash
set -e
cd /home/ubuntu/hcip
source .venv/bin/activate

nohup uvicorn api.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 2 \
    --log-level info \
    > /home/ubuntu/hcip/api.log 2>&1 &
echo $! > /home/ubuntu/hcip/api.pid
echo "Started PID: $(cat /home/ubuntu/hcip/api.pid)"
sleep 12
tail -15 /home/ubuntu/hcip/api.log
curl -s http://localhost:8000/health
