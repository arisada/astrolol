#!/bin/sh
# Demo container entrypoint: every start begins from the seed in /app/docker/demo.
# The data dir is a tmpfs (see docker-compose.yml), so nothing survives a restart.
set -e
data="${ASTROLOL_DATA_DIR:-/data}"
mkdir -p "$data"
cp /app/docker/demo/profiles.json /app/docker/demo/inventory.json "$data/"
exec "$@"
