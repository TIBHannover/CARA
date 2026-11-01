#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh

OUT=outputs/paper_analysis

run_python experiments/analyze_simulation.py outputs/paper/* --out "${OUT}"
run_python experiments/paper_table.py "${OUT}" --out "${OUT}"
