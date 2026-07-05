#!/bin/bash
set -e

echo "=== Installing Node.js 20 ==="
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs -q
node --version
npm --version

echo "=== Creating frontend directory ==="
mkdir -p /home/ubuntu/hcip-frontend

echo "=== Done — ready for files ==="
