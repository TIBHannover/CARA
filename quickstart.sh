#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
export MSYS_NO_PATHCONV=1

create_env_file() {
  [[ -f .env ]] && return
  cp .env.example .env
  sed -i.bak "s|^CARA_SECRET_KEY=.*|CARA_SECRET_KEY=$(openssl rand -hex 32)|" .env
  sed -i.bak "s|^CARA_ADMIN_PASSWORD=.*|CARA_ADMIN_PASSWORD=$(openssl rand -hex 8)|" .env
  rm -f .env.bak
}

build_toy_dataset() {
  [[ -f data/toy/cara.yaml ]] && return
  mkdir -p data
  docker compose run --rm --no-deps --user "$(id -u):$(id -g)" -v ./data:/out \
    -v ./experiments/make_toy_dataset.py:/tmp/make_toy_dataset.py:ro backend \
    python /tmp/make_toy_dataset.py /out/toy
}

load_toy_study() {
  docker compose exec -T backend cara user-add alice --password alice 2> /dev/null || echo "user alice exists"
  docker compose exec -T backend cara load /data/toy --member alice 2> /dev/null ||
    echo "the toy study is already loaded"
}

print_login() {
  local admin password
  admin="$(sed -n 's/^CARA_ADMIN_USERNAME=//p' .env)"
  password="$(sed -n 's/^CARA_ADMIN_PASSWORD=//p' .env)"
  if [[ -n "${password}" ]]; then
    echo "CARA is running: http://localhost:8501"
    echo "Log in as ${admin:-admin}, with the password CARA_ADMIN_PASSWORD in .env"
  else
    echo "CARA is running: http://localhost:8501. No CARA_ADMIN_PASSWORD in .env: create an admin with"
    echo "  docker compose exec backend cara user-add admin --superuser"
  fi
}

create_env_file
case "${1:-}" in
  --toy)
    docker compose build
    build_toy_dataset
    docker compose up -d --wait
    load_toy_study
    ;;
  "")
    docker compose up -d --build --wait
    ;;
  *)
    echo "usage: bash quickstart.sh [--toy]" >&2
    exit 1
    ;;
esac
print_login
