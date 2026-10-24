#!/usr/bin/env bash
# Usage: ./deploy.sh [local|databricks] [app-name] [profile]
set -euo pipefail
cd "$(dirname "$0")"
TARGET="${1:-local}"; APP="${2:-data-mesh-control-plane}"; PROFILE="${3:-}"

if [ "$TARGET" = "local" ]; then
  [ -d .venv ] || python3 -m venv .venv
  .venv/bin/python -m pip install -q -r requirements.txt
  export DB_BACKEND=sqlite SQLITE_PATH="$PWD/data/mesh.db" HOST=127.0.0.1 PORT="${PORT:-8000}"
  echo "Starting on http://localhost:$PORT (SQLite: $SQLITE_PATH)"
  exec .venv/bin/python app.py
fi

P=(); [ -n "$PROFILE" ] && P=(--profile "$PROFILE")
USER_NAME=$(databricks current-user me -o json "${P[@]}" | python3 -c "import sys,json;print(json.load(sys.stdin)['userName'])")
SRC="/Workspace/Users/$USER_NAME/apps/$APP"
databricks apps get "$APP" "${P[@]}" >/dev/null 2>&1 || databricks apps create "$APP" "${P[@]}"
databricks sync . "$SRC" --full "${P[@]}"
databricks apps deploy "$APP" --source-code-path "$SRC" "${P[@]}"
echo "Ensure a Lakebase database resource with key 'postgres' is attached to the app (see app.yaml)."
