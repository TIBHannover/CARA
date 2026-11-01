#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh

BASE_URL=http://ptak.felk.cvut.cz/met/dataset
DATABASE_ARCHIVE="${MET_DATABASE:-MET}"

fetch_and_unpack() {
  local archive="$1.tar.gz" target="$2"
  if [[ -f "${MET_ROOT}/.${archive}.done" ]]; then
    echo "${archive} is already unpacked"
    return
  fi
  curl -fL --retry 5 -C - -o "${MET_ROOT}/${archive}" "${BASE_URL}/${archive}"
  tar xzf "${MET_ROOT}/${archive}" -C "${target}"
  touch "${MET_ROOT}/.${archive}.done"
  rm "${MET_ROOT:?}/${archive:?}"
}

database_file() {
  if [[ "${DATABASE_ARCHIVE}" == small_MET ]]; then
    echo mini_MET_database.json
  else
    echo MET_database.json
  fi
}

mkdir -p "${MET_ROOT}/images" "${MET_ROOT}/ground_truth"
fetch_and_unpack ground_truth "${MET_ROOT}/ground_truth"
fetch_and_unpack test_met "${MET_ROOT}/images"
fetch_and_unpack "${DATABASE_ARCHIVE}" "${MET_ROOT}/images"
uv run --no-project python experiments/check_met_download.py "${MET_ROOT}" "$(database_file)"
