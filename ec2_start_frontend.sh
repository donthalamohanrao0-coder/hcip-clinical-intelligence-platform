#!/bin/bash
set -e
cd /home/ubuntu/hcip-frontend/.next/standalone

# Kill any existing Next.js process (Next renames its process title to "next-server", so match both)
pkill -f "node server.js" 2>/dev/null || true
pkill -f "next-server" 2>/dev/null || true
sleep 1

echo "=== Starting Next.js frontend on port 3000 ==="
export HCIP_API_URL="http://localhost:8000"
# Replace with one of the raw keys from your own API_KEYS entry in .env
export HCIP_API_KEY="REPLACE_WITH_YOUR_API_KEY"
export NEXT_PUBLIC_DEFAULT_KB_ID="kb-clinical-2024"
export PORT=3000
export HOSTNAME="0.0.0.0"
export NODE_ENV=production

nohup node server.js > /home/ubuntu/frontend.log 2>&1 &
echo $! > /home/ubuntu/frontend.pid
echo "Frontend PID: $(cat /home/ubuntu/frontend.pid)"

sleep 5
echo "=== Last 10 log lines ==="
tail -10 /home/ubuntu/frontend.log

echo "=== Health check ==="
curl -s -o /dev/null -w "HTTP %{http_code}" http://localhost:3000 || echo " (not ready yet)"
echo ""
echo "Frontend URL: http://$(curl -s -m 3 http://checkip.amazonaws.com):3000"
