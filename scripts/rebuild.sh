#!/usr/bin/env bash
# rebuild.sh — Rebuild and restart the api and worker containers, then verify health.

set -euo pipefail

echo "Building api and worker images..."
docker compose build api worker

echo "Starting api and worker (detached, no dependent restarts)..."
docker compose up -d --no-deps api worker

echo "Waiting for API to be ready..."
sleep 5

echo "Checking API health..."
curl -s http://localhost:8000/health | python3 -m json.tool
