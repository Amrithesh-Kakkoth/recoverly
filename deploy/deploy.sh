#!/usr/bin/env bash
# Runs on the server. Deploys one commit's published images, checks health, and rolls back if unhealthy.
# Usage: deploy.sh <full commit sha> [repo path, default: recoverly under $HOME]
set -euo pipefail

sha="${1:?commit sha required}"
repo="${2:-recoverly}"
[[ "$sha" =~ ^[0-9a-f]{40}$ ]] || { echo "not a full commit sha: $sha" >&2; exit 2; }
cd "$HOME"
cd "$repo"

state=.deployed-sha
compose=(docker compose -f docker-compose.yml -f docker-compose.prod.yml)

release() {
  git fetch --quiet origin
  git checkout --quiet --detach "$1"
  IMAGE_TAG="$1" "${compose[@]}" pull --quiet
  IMAGE_TAG="$1" "${compose[@]}" up -d --no-build --remove-orphans
}

healthy() {
  for _ in $(seq 1 40); do
    if curl -fsS http://127.0.0.1:8000/health > /dev/null \
      && curl -fsS http://127.0.0.1:3000/ > /dev/null \
      && curl -fsS http://127.0.0.1:8000/api/demo-config > /dev/null; then
      return 0
    fi
    sleep 3
  done
  return 1
}

previous="$(cat "$state" 2>/dev/null || true)"
echo "Deploying $sha (previous: ${previous:-none})"
release "$sha"

if healthy; then
  echo "$sha" > "$state"
  echo "Deployed $sha"
  exit 0
fi

echo "Health check failed for $sha" >&2
"${compose[@]}" logs --tail 50 app web >&2 || true
if [[ -n "$previous" && "$previous" != "$sha" ]]; then
  echo "Rolling back to $previous" >&2
  release "$previous"
  healthy && echo "Rolled back to $previous" >&2 || echo "Rollback is unhealthy too" >&2
else
  echo "No earlier deploy to roll back to" >&2
fi
exit 1
