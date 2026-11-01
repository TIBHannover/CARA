load_dotenv() {
  [[ -f .env ]] || return 0
  local key value
  while IFS='=' read -r key value; do
    [[ -z "${key}" || "${key}" == \#* || -n "${!key:-}" ]] && continue
    value="${value%$'\r'}"
    value="${value%%[[:space:]]#*}"
    value="${value%"${value##*[![:space:]]}"}"
    if [[ -n "${value}" ]]; then
      export "${key}=${value}"
    fi
  done < .env
}

cpu_count() {
  getconf _NPROCESSORS_ONLN 2> /dev/null || echo 4
}

default_image_loaders() {
  if [[ "$(uname -s)" == Linux ]]; then echo 4; else echo 0; fi
}

run_python() {
  uv run --project backend --extra encode --extra experiments python "$@"
}

load_dotenv
export PYTHONUTF8=1
export MSYS_NO_PATHCONV=1
export DATA="${DATA:-data}"
export MET_ROOT="${MET_ROOT:-${DATA}/met_source}"
export MET_OBJECTS="${MET_OBJECTS:-${DATA}/MetObjects.csv}"
export CACHE_DIR="${CACHE_DIR:-outputs/cache}"
BATCH_SIZE="${BATCH_SIZE:-128}"
ENCODER="${ENCODER:-dinov3-7b}"
LOADERS="${LOADERS:-$(default_image_loaders)}"
WORKERS="${WORKERS:-$(cpu_count)}"
