#!/bin/bash
# Install hcip-api and hcip-frontend as systemd services so they survive reboots.
# Copy this file + hcip-api.service + hcip-frontend.service to the EC2 host, then run it there.
set -e

echo "=== Stopping any manually-started (nohup) processes ==="
pkill -f "uvicorn api.main:app" 2>/dev/null || true
pkill -f "node server.js" 2>/dev/null || true
sleep 1

echo "=== Installing unit files ==="
sudo cp /home/ubuntu/hcip-api.service /etc/systemd/system/hcip-api.service
sudo cp /home/ubuntu/hcip-frontend.service /etc/systemd/system/hcip-frontend.service
sudo systemctl daemon-reload

echo "=== Enabling + starting services ==="
sudo systemctl enable --now hcip-api
sudo systemctl enable --now hcip-frontend

sleep 5
echo "=== Status ==="
sudo systemctl --no-pager status hcip-api hcip-frontend

echo "=== Health checks ==="
curl -s http://localhost:8000/health
echo ""
curl -s -o /dev/null -w "frontend HTTP %{http_code}\n" http://localhost:3000
