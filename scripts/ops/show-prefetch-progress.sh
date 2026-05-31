#!/usr/bin/env bash
# Show prefetch progress in the terminal until complete.
# Usage: ./scripts/ops/show-prefetch-progress.sh [API_HOST] [TOKEN]

set -euo pipefail

API="${1:-http://127.0.0.1:1349}"
TOKEN="${2:-droplet_dev_admin}"

# Wait for API to be ready
for i in $(seq 1 30); do
    if curl -sf --noproxy '*' -H "Authorization: Bearer $TOKEN" "$API/api/health" >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

# Poll prefetch progress
while true; do
    data=$(curl -sf --noproxy '*' -H "Authorization: Bearer $TOKEN" "$API/api/challenges/prefetch/progress" 2>/dev/null) || { sleep 2; continue; }

    running=$(echo "$data" | python3 -c "import sys,json; print(json.load(sys.stdin).get('running',False))" 2>/dev/null) || { sleep 2; continue; }

    if [ "$running" != "True" ]; then
        # Check if prefetch ever ran (total > 0 means it completed)
        total=$(echo "$data" | python3 -c "import sys,json; print(json.load(sys.stdin).get('total',0))" 2>/dev/null)
        if [ "$total" != "0" ]; then
            pulled=$(echo "$data" | python3 -c "import sys,json; print(json.load(sys.stdin).get('pulled',0))" 2>/dev/null)
            errors=$(echo "$data" | python3 -c "import sys,json; print(json.load(sys.stdin).get('errors',0))" 2>/dev/null)
            echo ""
            echo -e "  \033[32m✓\033[0m 预热完成  拉取 $pulled 个镜像  错误 $errors 个"
            break
        fi
        # Prefetch hasn't started yet, keep waiting
        sleep 1
        continue
    fi

    current=$(echo "$data" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('current',0))" 2>/dev/null)
    total=$(echo "$data" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('total',0))" 2>/dev/null)
    cid=$(echo "$data" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('current_id','').upper())" 2>/dev/null)
    pulled=$(echo "$data" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('pulled',0))" 2>/dev/null)

    # Build progress bar
    pct=0
    if [ "$total" -gt 0 ] 2>/dev/null; then
        pct=$((current * 100 / total))
    fi
    bar_width=30
    filled=$((pct * bar_width / 100))
    empty=$((bar_width - filled))
    bar=$(printf "%${filled}s" | tr ' ' '█')$(printf "%${empty}s" | tr ' ' '░')

    printf "\r  \033[36m⟳\033[0m 镜像预热  [%s] %3d%%  %d/%d  %s  " "$bar" "$pct" "$current" "$total" "$cid"

    sleep 1
done
