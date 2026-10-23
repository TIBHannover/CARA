#!/bin/bash
# From a fresh clone to a running CARA with Docker. Then open http://localhost:8501.
#
#   bash quickstart.sh          an empty CARA: log in as admin and follow the set-up guide; keeps what is there
#   bash quickstart.sh --toy    the same, plus the toy dataset and study (annotator alice/alice)
#   bash quickstart.sh --demo   DELETES THE DATABASE, then loads the Met demo (needs demo_load.sh and its data)
#
# The admin's password is generated into .env on the first run (CARA_ADMIN_PASSWORD).
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -f .env ]]; then
  cp .env.example .env
  key="$(openssl rand -hex 32)"
  password="$(openssl rand -hex 8)"
  # -i.bak works with both GNU sed (Linux) and BSD sed (macOS)
  sed -i.bak "s|^CARA_SECRET_KEY=.*|CARA_SECRET_KEY=${key}|; s|^CARA_ADMIN_PASSWORD=.*|CARA_ADMIN_PASSWORD=${password}|" .env
  rm -f .env.bak
fi
cara() { docker compose exec -T backend cara "$@"; }
case "${1:-}" in
  --demo)
    if [[ ! -f demo_load.sh ]]; then
      echo "--demo needs demo_load.sh and the Met demo data, which this copy of CARA doesn't have; use --toy" >&2
      exit 1
    fi
    docker compose down -v
    docker compose up -d --build --wait
    CARA="docker compose exec -T backend cara" DATA_IN=/data bash demo_load.sh
    echo "CARA is running: http://localhost:8501 (admin: password CARA_ADMIN_PASSWORD in .env, else admin;"
    echo "annotators alice/alice and pilot/pilot)"
    exit 0
    ;;
  --toy)
    docker compose build
    if [[ ! -f data/toy/cara.yaml ]]; then
      # Drawn inside the backend image (it has numpy and Pillow), as the current user, so the files stay yours.
      mkdir -p data
      docker compose run --rm --no-deps --user "$(id -u):$(id -g)" -v ./data:/out \
        -v ./experiments/make_toy_dataset.py:/tmp/make_toy_dataset.py:ro backend \
        python /tmp/make_toy_dataset.py /out/toy
    fi
    docker compose up -d --wait
    cara user-add alice --password alice 2> /dev/null || echo "user alice exists"
    cara load /data/toy --member alice 2> /dev/null || echo "the toy study is already loaded"
    ;;
  *)
    docker compose up -d --build --wait
    ;;
esac
admin="$(sed -n 's/^CARA_ADMIN_USERNAME=//p' .env)"
password="$(sed -n 's/^CARA_ADMIN_PASSWORD=//p' .env)"
if [[ -n "${password}" ]]; then
  echo "CARA is running: http://localhost:8501 (log in as ${admin:-admin}, password in .env: CARA_ADMIN_PASSWORD)"
else
  echo "CARA is running: http://localhost:8501. No CARA_ADMIN_PASSWORD in .env: create an admin with"
  echo "  docker compose exec backend cara user-add admin --superuser"
fi
