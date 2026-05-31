#!/usr/bin/env python3
"""Display prefetch progress in the terminal banner area.

Usage: python3 scripts/ops/prefetch-tui.py <row> [api_url] [token]
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request

SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


def main() -> None:
    row = int(sys.argv[1]) if len(sys.argv) > 1 else 13
    api = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:1349"
    token = sys.argv[3] if len(sys.argv) > 3 else "droplet_dev_admin"
    bar_w = 20

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    headers = {"Authorization": f"Bearer {token}"}

    # Phase 1: Wait for API with animated spinner
    spin_i = 0
    for _ in range(60):
        _write(row, f"  \033[1mPrefetch\033[0m   \033[36m{SPINNER[spin_i % len(SPINNER)]}\033[0m \033[2m等待后端启动...\033[0m   ")
        spin_i += 1
        try:
            req = urllib.request.Request(f"{api}/api/health", headers=headers)
            opener.open(req, timeout=2)
            break
        except Exception:
            time.sleep(1)
    else:
        _write(row, "  \033[1mPrefetch\033[0m   \033[33m⚠\033[0m 后端未响应，跳过预热   ")
        return

    # Phase 2: Poll prefetch progress
    while True:
        try:
            req = urllib.request.Request(f"{api}/api/challenges/prefetch/progress", headers=headers)
            with opener.open(req, timeout=3) as resp:
                data = json.loads(resp.read())
        except Exception:
            time.sleep(2)
            continue

        running = data.get("running", False)
        total = data.get("total", 0)
        current = data.get("current", 0)
        pulled = data.get("pulled", 0)
        errors = data.get("errors", 0)
        cid = (data.get("current_id") or "").upper()

        if not running:
            if total > 0:
                _write(row, f"  \033[1mPrefetch\033[0m   \033[32m✓\033[0m 完成  拉取 {pulled}  错误 {errors}   ")
            else:
                # Prefetch hasn't started yet, show waiting animation
                _write(row, f"  \033[1mPrefetch\033[0m   \033[36m{SPINNER[spin_i % len(SPINNER)]}\033[0m \033[2m准备中...\033[0m   ")
                spin_i += 1
                time.sleep(0.5)
                continue
            break

        pct = (current * 100 // total) if total > 0 else 0
        filled = pct * bar_w // 100
        bar = "\033[36m" + "█" * filled + "\033[0m" + "░" * (bar_w - filled)
        _write(row, f"  \033[1mPrefetch\033[0m   \033[36m{SPINNER[spin_i % len(SPINNER)]}\033[0m [{bar}] {pct:3d}%  {current}/{total}  \033[2m{cid}\033[0m   ")
        spin_i += 1
        time.sleep(1)


def _write(row: int, text: str) -> None:
    """Write text to a specific terminal row using ANSI save/restore cursor."""
    sys.stdout.write(f"\0337\033[{row + 1};1H\033[2K{text}\0338")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
