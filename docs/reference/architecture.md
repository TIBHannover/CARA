# Architecture

```
backend/            FastAPI, SQLAlchemy 2, Postgres + pgvector, Alembic
  src/cara/core/    pure functions: agreement, exports, pools, suggestions, pilot statistics (no database, no web)
  src/cara/grouping/  one module per grouping method; base.py has what they share and the registry
  src/cara/encoders/  one module per encoder (clip.py, dinov3.py, siglip.py, huggingface.py); base.py has the registry
  src/cara/         settings (studies), config (CARA_* env), errors, inputs, simulation/, db/, repositories/, services/, api/, cli.py
frontend/           Streamlit; client.py is the only module that talks to the API
experiments/        simulation study and dataset builders (not needed to run the tool)
configs/            Hydra configs for the simulation study
```

Dependencies point one way: `api → services → repositories → db`, and `services → core`.

| Layer | Holds | Shape |
|---|---|---|
| `api/` | routes, request and response schemas, authentication | each route takes the service it needs as a dependency (`api/deps.py`) |
| `services/` | the rules: who sees what, what locks when, how pools are built | one class per area (`StudyService`, `AnnotationService`, ...), each working on a `Database` |
| `repositories/` | every database query, and the image files | `Repository[T]` with four aggregates (`Users`, `Datasets`, `Studies`, `Judgments`) gathered in a `Database`, the unit of work; `ImageStore` for the files |
| `core/` | pure functions: agreement, exports, pools, suggestions, pilot statistics | no database, no web |
| `grouping/`, `encoders/` | the two extension points | one module per method or encoder, each class registered with `@register` (see below) |
| `cli.py` | the `cara` command | an entry point like `api/`: parses arguments, runs one command in one transaction, calls services |
| `settings.py` | what a study can be configured with | pydantic models, read from YAML or the admin pages ([Study settings](settings.md)) |
| `config.py` | how the server runs | `AppSettings`, a pydantic-settings `BaseSettings` read from the `CARA_*` variables once at startup |
| `inputs.py` | the dataset files | pydantic models and readers for query, corpus and embedding files; errors name the file and line |

A study's `grouping.method` picks a grouping class, through the `GroupingSettings` union. The part of an encoder's
name before `:` picks an encoder class, through `build_encoder`.

Errors (`cara/errors.py`): `NotFound`, `Forbidden`, `Conflict` and `Invalid`, which the API answers with 404, 403,
409 and 422. Services raise them with a message that says what is wrong and, where it can, what fixes it; the CLI
prints the same message.

## Repositories

All SQL lives in `repositories/`, one class per aggregate root, not per table: the rows that only make sense
through a study (its labels, queries, pools and pool members) are queried through `Studies`.

| Repository | Holds |
|---|---|
| `Users` | accounts and study membership |
| `Datasets` | images, embeddings (pgvector, with an HNSW index per encoder), query sets, nearest neighbours |
| `Studies` | studies with their labels, queries, pools and members |
| `Judgments` | judgments, the action log, assignments, adjudications |

Every repository has `find`, `get` (raising `NotFound` with the noun and id), `add` and `list_all`, and its own
queries. Repositories flush but never commit: the caller owns the transaction, one per API request and one per
CLI command, so an operation is saved whole or not at all. One rule stays in SQL: a group label never overwrites
an image labelled one by one, checked in the upsert itself so it holds when two clicks race.

The schema is defined by the Alembic migrations in `backend/migrations/versions/`; the API applies them when it
starts.

The simulation engine (`cara/simulation/`) has one entry point, `simulate_pool`: each simulated annotator type
decides its own steps, and a workflow (grouped judging or Suggest mode) asks it. The app's simulator
(`services/simulator/`) and the simulation study (`experiments/`) both call it.
