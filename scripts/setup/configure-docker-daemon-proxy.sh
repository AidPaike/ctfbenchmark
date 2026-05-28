#!/usr/bin/env bash
set -euo pipefail

PROXY="${1:-${DROPLET_DOCKER_PROXY:-http://192.168.3.67:7890}}"
NO_PROXY="${DROPLET_DOCKER_NO_PROXY:-127.0.0.1,localhost,::1,host.docker.internal,pypi.tuna.tsinghua.edu.cn}"
DROPIN_DIR="/etc/systemd/system/docker.service.d"
DROPIN_FILE="$DROPIN_DIR/http-proxy.conf"

sudo python3 - <<'INNER_PY'
from pathlib import Path
import json
import time

path = Path('/etc/docker/daemon.json')
if path.exists():
    text = path.read_text(encoding='utf-8')
    data = json.loads(text or '{}')
else:
    text = ''
    data = {}

mirrors = data.get('registry-mirrors')
if isinstance(mirrors, list) and mirrors:
    backup = path.with_name(f'{path.name}.bak.{int(time.time())}')
    backup.write_text(text, encoding='utf-8')
    data.pop('registry-mirrors', None)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'Removed registry mirrors so Docker Hub pulls use the daemon proxy; backup: {backup}')
INNER_PY

sudo mkdir -p "$DROPIN_DIR"
sudo tee "$DROPIN_FILE" >/dev/null <<EOF
[Service]
Environment="HTTP_PROXY=$PROXY"
Environment="HTTPS_PROXY=$PROXY"
Environment="NO_PROXY=$NO_PROXY"
EOF

sudo systemctl daemon-reload
sudo systemctl restart docker

docker info | sed -n '/HTTP Proxy/,+8p'
