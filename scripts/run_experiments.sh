#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -z "${SKIP_PREPARE:-}" ]]; then
  bash scripts/download_met.sh
  bash scripts/build_datasets.sh
fi
bash scripts/simulate.sh
bash scripts/analyze.sh
