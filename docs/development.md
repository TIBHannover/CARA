# Development

## Running from source

```bash
docker compose up -d db
cd backend && uv venv --python 3.12 && uv pip install -e ".[dev]"
set -a && . ../.env && set +a
export CARA_DATABASE_URL=postgresql+psycopg://cara:cara@localhost:5432/cara CARA_IMAGE_ROOT=$PWD/../data
.venv/bin/alembic upgrade head && .venv/bin/fastapi dev            # API with reload
cd ../frontend && uv sync && CARA_API_URL=http://localhost:8000 .venv/bin/streamlit run main.py
```

On Windows, the virtual environment's programs are in `.venv/Scripts/`.

## Checks

In `backend/`, run `ruff format . && ruff check . && mypy && pytest -q`. In `frontend/`, run
`ruff format . && ruff check . && mypy`.

The backend tests need Postgres with pgvector. `docker compose up -d db` creates a `cara_test` database next to `cara`
on its first start. Set `CARA_TEST_DATABASE_URL` to use another one.

## Documentation

These pages are Markdown in `docs/`, with the navigation in `mkdocs.yml`:

```bash
docker compose --profile docs up -d docs     # http://localhost:8002/CARA/
```

The glossary is `GLOSSARY.md` at the repository root.
