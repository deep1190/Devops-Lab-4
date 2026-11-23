#!/usr/bin/env bash
# Seeds Vault with the app secret, a least-privilege read-only policy, and an AppRole for the pipeline.
# Run after: docker compose -f docker-compose.vault.yml up -d
set -euo pipefail
export VAULT_ADDR=http://127.0.0.1:8200 VAULT_TOKEN=dev-root-token
V="docker compose -f $(dirname "$0")/docker-compose.vault.yml exec -T -e VAULT_ADDR=http://127.0.0.1:8200 -e VAULT_TOKEN=dev-root-token vault vault"

# 1. store the secret (value generated, never typed into a file)
$V kv put secret/notes-app api-token="$(openssl rand -hex 24)"

# 2. least-privilege policy: read only this one path
$V policy write notes-app-read - <<'EOF'
path "secret/data/notes-app" { capabilities = ["read"] }
EOF

# 3. AppRole for CI/deployments (short-lived tokens, 15 min)
$V auth enable approle || true
$V write auth/approle/role/ci-pipeline token_policies=notes-app-read token_ttl=15m token_max_ttl=30m
echo "role_id:";    $V read -field=role_id auth/approle/role/ci-pipeline/role-id
echo "secret_id (store this in GitHub Actions secrets, not in Git):"
$V write -f -field=secret_id auth/approle/role/ci-pipeline/secret-id
