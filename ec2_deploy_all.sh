#!/bin/bash
# Deploy updated FastAPI + frontend to EC2
# Run from the project root: bash ec2_deploy_all.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KEY="$SCRIPT_DIR/hcip-key.pem"
HOST_IP="$(grep -m1 '^PUBLIC_IP=' "$SCRIPT_DIR/ec2_info.txt" | cut -d= -f2)"
HOST="ubuntu@$HOST_IP"

echo "=== 1. Installing pypdf on EC2 ==="
ssh -i "$KEY" -o StrictHostKeyChecking=no $HOST \
  "source /home/ubuntu/hcip/.venv/bin/activate && pip install pypdf>=4.0 -q && echo 'pypdf OK'"

echo "=== 2. Copying updated FastAPI files ==="
scp -i "$KEY" -o StrictHostKeyChecking=no \
  "$SCRIPT_DIR/api/routers/ingest.py" \
  $HOST:/home/ubuntu/hcip/api/routers/ingest.py

scp -i "$KEY" -o StrictHostKeyChecking=no \
  "$SCRIPT_DIR/api/main.py" \
  $HOST:/home/ubuntu/hcip/api/main.py

echo "=== 3. Restarting FastAPI ==="
ssh -i "$KEY" -o StrictHostKeyChecking=no $HOST \
  "sudo systemctl restart hcip-api || bash /home/ubuntu/ec2_start_api.sh"

echo "=== 4. Copying new frontend bundle ==="
scp -i "$KEY" -o StrictHostKeyChecking=no \
  "$SCRIPT_DIR/frontend/frontend-standalone.tar.gz" \
  $HOST:/home/ubuntu/frontend-standalone.tar.gz

echo "=== 5. Extracting and restarting frontend ==="
ssh -i "$KEY" -o StrictHostKeyChecking=no $HOST bash << 'ENDSSH'
set -e
sudo systemctl stop hcip-frontend 2>/dev/null || pkill -f "node server.js" 2>/dev/null || echo "Stopped old frontend"

mkdir -p /home/ubuntu/hcip-frontend
cd /home/ubuntu
tar -xzf frontend-standalone.tar.gz -C /home/ubuntu/hcip-frontend/ --strip-components=1
echo "Extracted frontend"

sudo systemctl start hcip-frontend 2>/dev/null || bash /home/ubuntu/ec2_start_frontend.sh
ENDSSH

echo "=== Done! ==="
echo "Frontend: http://$HOST_IP:3000"
echo "FastAPI:  http://$HOST_IP:8000"
