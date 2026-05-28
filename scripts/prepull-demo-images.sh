#!/usr/bin/env bash
set -euo pipefail

images=(
  "debian:bullseye-slim"
  "mysql:5.7"
  "python:2.7-slim-stretch"
  "python:3.12"
)

for image in "${images[@]}"; do
  docker pull "$image"
done
