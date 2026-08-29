#!/usr/bin/env bash
# Full-sync deploy of the committed tree to the eucshare droplet.
#
#   ./scripts/deploy.sh              # deploy HEAD (must equal origin/main)
#   ./scripts/deploy.sh --check      # verify only, change nothing
#
# Ships EVERY tracked file, not a hand-picked subset. A selective file-push once
# half-applied and broke all uploads; `git archive` of a commit cannot do that,
# because the deployed tree is exactly that commit. data/, .venv/ and anything in
# .gitignore are never in the archive, so live data and secrets are untouched.
#
# Auth is whatever ssh already uses - an installed key, or it prompts you for the
# password. Nothing is stored or echoed by this script.
set -euo pipefail

HOST="${EUCSHARE_HOST:-root@64.227.89.199}"
APP="${EUCSHARE_APP_DIR:-/opt/eucshare}"
SERVICE="${EUCSHARE_SERVICE:-eucshare}"
URL="${EUCSHARE_URL:-https://eucshare.ried.no}"

verify() {
    echo
    echo "--- verifying ---"
    local body
    body=$(curl -s --max-time 20 "$URL/health" || echo "")
    case "$body" in
        *'"ok":true'*|*'"ok": true'*) echo "  /health                 : $body OK" ;;
        "")                           echo "  /health                 : FAILED (no response)" ;;
        *)                            echo "  /health                 : $body FAILED" ;;
    esac
    ssh "$HOST" "systemctl is-active $SERVICE" 2>/dev/null \
        | sed 's/^/  service                 : /' || echo "  service                 : unknown"
}

if [ "${1:-}" = "--check" ]; then
    verify
    exit 0
fi

# Deploy only what is committed AND pushed, so the server always matches a commit
# you can point at later.
if [ -n "$(git status --porcelain)" ]; then
    echo "working tree is dirty - commit or stash first:" >&2
    git status --short >&2
    exit 1
fi
git fetch -q origin
local_sha=$(git rev-parse HEAD)
remote_sha=$(git rev-parse origin/main)
if [ "$local_sha" != "$remote_sha" ]; then
    echo "HEAD is not origin/main - push first" >&2
    echo "  HEAD        $local_sha" >&2
    echo "  origin/main $remote_sha" >&2
    exit 1
fi

echo "deploying to $HOST:$APP"
git log --oneline -1 | sed 's/^/  /'
echo

echo "[1/4] first-run bootstrap (creates .venv if missing, otherwise a no-op)"
ssh "$HOST" "mkdir -p '$APP' && [ -x '$APP/.venv/bin/python' ] || python3 -m venv '$APP/.venv'"

echo "[2/4] syncing tracked files"
git archive HEAD | ssh "$HOST" "mkdir -p '$APP' && tar -x -C '$APP'"

echo "[3/4] installing deps (no cache - the droplet root fills up)"
ssh "$HOST" "cd '$APP' && .venv/bin/pip install --quiet --no-cache-dir -r requirements.txt"

echo "[4/4] clearing stale bytecode and restarting"
ssh "$HOST" "find '$APP' -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null; systemctl restart '$SERVICE' 2>&1 || echo '  (service not installed yet - expected on first run)'"

sleep 3
verify

cat <<'NOTE'

Note: this adds and overwrites tracked files but does not delete files that were
removed from git. That is deliberate - nothing is rm -rf'd on a live box. If a
file is ever deleted in a commit, remove it on the server by hand.
NOTE
