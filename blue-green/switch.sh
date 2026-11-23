#!/usr/bin/env bash
# Usage: ./switch.sh green|blue
# 1) health-check the target  2) rewrite active.conf  3) validate + graceful reload  4) smoke test
set -euo pipefail
TARGET="${1:?usage: switch.sh blue|green}"
cd "$(dirname "$0")"

echo "Checking $TARGET is healthy before switching..."
docker compose exec -T "app-$TARGET" python -c \
  "import urllib.request;assert urllib.request.urlopen('http://localhost:5000/health').status==200"

echo "map \$host \$active_env { default $TARGET; }" > active.conf
docker compose exec -T router nginx -t
docker compose exec -T router nginx -s reload      # graceful: old workers finish in-flight requests

sleep 1
SERVED=$(curl -si localhost:8080/version | grep -i x-served-by | tr -d '\r')
echo "Now live -> $SERVED"
echo "$SERVED" | grep -qi "$TARGET" || { echo "Smoke test failed"; exit 1; }
