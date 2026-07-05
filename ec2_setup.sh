#!/bin/bash
set -e
cd /home/ubuntu/hcip

echo "=== Installing python3.10-venv ==="
sudo apt-get install -y python3.10-venv -q

echo "=== Killing running API ==="
pkill -f "uvicorn api.main:app" 2>/dev/null || true
sleep 1

echo "=== Recreating venv with Python 3.10 ==="
rm -rf .venv
python3.10 -m venv .venv
source .venv/bin/activate
echo "Python: $(python --version)"

echo "=== Installing packages ==="
pip install --upgrade pip -q
pip install -r requirements-query.txt -q
echo "requirements-query.txt done"

echo "=== Installing FlagEmbedding ==="
pip install FlagEmbedding -q
python -c "from FlagEmbedding import FlagModel; print('FlagEmbedding OK')"

echo "=== Checking elasticsearch version ==="
python -c "import elasticsearch; print('elasticsearch:', elasticsearch.__version__)"

echo "=== Starting FastAPI ==="
nohup uvicorn api.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 2 \
    --log-level info \
    > /home/ubuntu/hcip/api.log 2>&1 &
echo $! > /home/ubuntu/hcip/api.pid
echo "FastAPI PID: $(cat /home/ubuntu/hcip/api.pid)"

echo "=== Waiting for startup ==="
sleep 15

echo "=== API log ==="
tail -20 /home/ubuntu/hcip/api.log

echo "=== Health check ==="
curl -s http://localhost:8000/health

echo ""
echo "=== Setup complete ==="
