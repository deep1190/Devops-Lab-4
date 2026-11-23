#!/usr/bin/env bash
# Usage: ./set_weight.sh 25      -> send 25% of traffic to canary (0 = rollback, 100 = promote)
set -euo pipefail
PCT="${1:?percentage 0-100}"
cd "$(dirname "$0")"
if   [ "$PCT" -le 0 ];   then printf 'split_clients "${remote_addr}${request_id}" $target_pool { * stable; }\n' > weights.conf
elif [ "$PCT" -ge 100 ]; then printf 'split_clients "${remote_addr}${request_id}" $target_pool { * canary; }\n' > weights.conf
else printf 'split_clients "${remote_addr}${request_id}" $target_pool {\n  %s%%  canary;\n  *    stable;\n}\n' "$PCT" > weights.conf
fi
docker compose exec -T router nginx -t && docker compose exec -T router nginx -s reload
echo "Canary now receives ${PCT}% of traffic"
