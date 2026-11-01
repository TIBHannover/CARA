#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh

simulate_dataset() {
  local dataset="$1"
  run_python experiments/simulate.py --config-name simulate "dataset=${dataset}" "workers=${WORKERS}" \
    "hydra.run.dir=outputs/paper/${dataset}"
}

simulate_dataset met_test
simulate_dataset met_text_test
simulate_dataset met_composed_test
