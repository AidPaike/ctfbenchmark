#!/usr/bin/env python3
"""Poll prefetch progress and write status to a file for the shell banner to read.

Usage: python3 scripts/ops/prefetch-tui.py <status_file> [api_url] [token]
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request

SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


def main() -> None:
    status_file = sys.argv[1] if len(sys.argv) > 1 else "/tmp/droplet-prefetch.status"
    api = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:1349"
    token = sys.argv[3] if len(sys.argv) > 3 else "droplet_dev_admin"
    bar_w = 20

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    headers = {"Authorization": f"Bearer {token}"}

    def write_status(text: str) -> None:
        try:
            with open(status_file, "w") as f:
                f.write(text)
        except OSError:
            pass

    # Phase 1: Wait for API
    spin_i = 0
    for _ in range(60):
        write_status(f"等待后端启动 {SPINNER[spin_i % len(SPINNER)]}")
        spin_i += 1
        try:
            req = urllib.request.Request(f"{api}/api/health", headers=headers)
            opener.open(req, timeout=2)
            break
        except Exception:
            time.sleep(1)
    else:
        write_status("后端未响应")
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
                write_status(f"✓ 完成  拉取 {pulled}  错误 {errors}")
            else:
                write_status(f"准备中 {SPINNER[spin_i % len(SPINNER)]}")
                spin_i += 1
                time.sleep(0.5)
                continue
            break

        pct = (current * 100 // total) if total > 0 else 0
        filled = pct * bar_w // 100
        bar = "█" * filled + "░" * (bar_w - filled)
        write_status(f"{SPINNER[spin_i % len(SPINNER)]} [{bar}] {pct:3d}%  {current}/{total}  {cid}")
        spin_i += 1
        time.sleep(1)


if __name__ == "__main__":
    main()
