#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh

encoder=clip
queries=10
pool_size=50
max_images=5000
folder="${DATA}/met_study"

print_usage() {
  echo "usage: bash scripts/met_study.sh [--encoder clip] [--queries 10] [--pool-size 50]" \
    "[--max-images 5000]" >&2
}

parse_options() {
  while (($#)); do
    case "$1" in
      --encoder) encoder="$2" ;;
      --queries) queries="$2" ;;
      --pool-size) pool_size="$2" ;;
      --max-images) max_images="$2" ;;
      *)
        print_usage
        exit 1
        ;;
    esac
    shift 2
  done
}

require_running_cara() {
  if ! docker compose exec -T backend true 2> /dev/null; then
    echo "CARA isn't running: start it with bash quickstart.sh" >&2
    exit 1
  fi
}

build_dataset() {
  rm -rf "${folder:?}"
  run_python experiments/build_met_dataset.py "${MET_ROOT}" "${folder}" --cache-dir "${CACHE_DIR}" --mini \
    --split test --queries "${queries}" --depth "${pool_size}" --encoder "${encoder}" \
    --max-images "${max_images}" --batch-size 32 --num-workers "${LOADERS}"
}

add_dataset_files() {
  mkdir -p "${folder}/qrels"
  cp "${folder}/ground_truth.qrels" "${folder}/qrels/default.qrels"
  cat > "${folder}/dataset.yaml" << YAML
name: The Met (mini)
description: The mini Met database and test queries, downloaded from the dataset's authors.
YAML
}

load_study() {
  docker compose exec -T backend cara user-add alice --password alice 2> /dev/null || echo "user alice exists"
  docker compose exec -T backend cara load /data/met_study --member alice
}

parse_options "$@"
require_running_cara
MET_DATABASE=small_MET bash scripts/download_met.sh
build_dataset
add_dataset_files
load_study
echo "The study is ready: http://localhost:8501"
