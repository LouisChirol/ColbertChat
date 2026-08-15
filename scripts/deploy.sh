#!/bin/bash
set -euo pipefail

# Production deploy for the shared Caddy + `web` network stack (lchirol-infra).
# Edge TLS and routing live in ~/lchirol/infra/Caddyfile — not in this repo's nginx/.

mkdir -p ~/turgot
cd ~/turgot

mkdir -p backend/logs
chmod 777 backend/logs

echo "Setting up environment files..."
cp frontend/.env.production frontend/.env

echo "Stopping existing containers..."
docker compose down

echo "Building and starting services..."
docker compose up -d --build frontend backend redis

docker compose ps

echo "Deployment complete!"
echo "  Primary URL: https://turgot.louischirol.fr"
echo "  API path:    https://turgot.louischirol.fr/api/"
echo "  Legacy API:  https://api.turgotchat.fr (kept for old clients)"
echo "Logs: ~/turgot/backend/logs/turgot_backend.log"
