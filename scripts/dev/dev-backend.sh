#!/usr/bin/env bash
set -euo pipefail

export PYTHONPATH="${PYTHONPATH:-}:backend:sdk"
export DROPLET_DOCKER_PROXY="${DROPLET_DOCKER_PROXY-http://192.168.3.67:7890}"
export DROPLET_DOCKER_NO_PROXY="${DROPLET_DOCKER_NO_PROXY:-127.0.0.1,localhost,::1,host.docker.internal,pypi.tuna.tsinghua.edu.cn}"
export DROPLET_COMPOSE_TIMEOUT_SECONDS="${DROPLET_COMPOSE_TIMEOUT_SECONDS:-300}"
if [[ -n "$DROPLET_DOCKER_PROXY" ]]; then
  export HTTP_PROXY="${HTTP_PROXY:-$DROPLET_DOCKER_PROXY}"
  export HTTPS_PROXY="${HTTPS_PROXY:-$DROPLET_DOCKER_PROXY}"
  export http_proxy="${http_proxy:-$DROPLET_DOCKER_PROXY}"
  export https_proxy="${https_proxy:-$DROPLET_DOCKER_PROXY}"
else
  unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy
fi
export NO_PROXY="${NO_PROXY:-$DROPLET_DOCKER_NO_PROXY}"
export no_proxy="${no_proxy:-$DROPLET_DOCKER_NO_PROXY}"
uvicorn droplet.app:app --host 127.0.0.1 --port 1349 --reload --reload-dir backend --reload-dir sdk --reload-exclude "data/work/*"
