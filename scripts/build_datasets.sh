#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh

OBJECTS_URL=https://media.githubusercontent.com/media/metmuseum/openaccess/master/MetObjects.csv

download_met_objects() {
  [[ -f "${MET_OBJECTS}" ]] && return
  mkdir -p "$(dirname "${MET_OBJECTS}")"
  curl -fL --retry 3 -o "${MET_OBJECTS}" "${OBJECTS_URL}"
}

build_image_dataset() {
  local folder="${DATA}/met_test_all"
  run_python experiments/build_met_dataset.py "${MET_ROOT}" "${folder}" --cache-dir "${CACHE_DIR}" \
    --split test --queries 0 --skip-images --encoder "${ENCODER}" --batch-size "${BATCH_SIZE}" \
    --num-workers "${LOADERS}"
  run_python experiments/write_met_category_qrels.py "${folder}" "${MET_OBJECTS}"
}

build_query_dataset() {
  local task="$1"
  run_python experiments/build_met_query_dataset.py "${MET_OBJECTS}" "${DATA}/met_${task}_test" \
    --task "${task}" --met-root "${MET_ROOT}" --split test --grouping "${ENCODER}" \
    --cache-dir "${CACHE_DIR}" --batch-size "${BATCH_SIZE}" --num-workers "${LOADERS}"
}

download_met_objects
build_image_dataset
build_query_dataset text
build_query_dataset composed
