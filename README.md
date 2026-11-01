<div align="center">

<img src="frontend/assets/logo-readme.svg" alt="CARA" width="300">

**Cluster-Assisted Relevance Assessment Tool for Image Retrieval Test Collections**

[![DOI](https://img.shields.io/badge/DOI-10.5281%2Fzenodo.23866166-blue.svg)](https://doi.org/10.5281/zenodo.23866166) [![CI](https://github.com/TIBHannover/CARA/actions/workflows/ci.yml/badge.svg)](https://github.com/TIBHannover/CARA/actions/workflows/ci.yml) [![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE) [![Version](https://img.shields.io/badge/version-0.1.0-brightgreen.svg)](https://github.com/TIBHannover/CARA) [![Python 3.12](https://img.shields.io/badge/python-3.12-3776AB.svg?logo=python&logoColor=white)](https://www.python.org) [![Docker Compose](https://img.shields.io/badge/docker-compose-2496ED.svg?logo=docker&logoColor=white)](compose.yaml) [![FastAPI](https://img.shields.io/badge/FastAPI-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com) [![Streamlit](https://img.shields.io/badge/Streamlit-FF4B4B.svg?logo=streamlit&logoColor=white)](https://streamlit.io)

</div>

CARA is an open-source tool for creating relevance judgments (qrels) for image retrieval test collections.
It shows each query's pool of candidates in groups of visually similar images, clustered on image embeddings, so
an annotator labels a whole group with one click and overrides single images where a group is mixed. Every
candidate still gets its own label. Queries can be images, text, or both (composed retrieval).

Before judging starts, a built-in simulator replays your queries with simulated annotators and shows how much
time each grouping setting saves and how much recall it costs. Judgments export as TREC qrels, per annotator and
by consensus.

![The judge page: the query on the left, its pool in groups of similar images on the right](docs/assets/screenshots/judge.webp)
<p align="center"><em>The judge page on the toy dataset: the query on the left, its pool in groups of similar images on the right.</em></p>

**[Documentation](https://tibhannover.github.io/CARA/)**

## Features

- **Candidate sampling.** Pools from existing runs, the nearest neighbours of one or more encoders, or a random sample.
- **Group, then correct.** Label a group with one click, override single images, split mixed groups.
- **Suggest mode.** After a few marked images, similar unjudged images get a suggested label.
- **Review round.** A labelled pool sorted by label, where missed Relevant images are easiest to spot.
- **Simulate before you judge.** Estimate how much time each grouping setting saves and how much recall it costs.
- **Pilot and guidelines.** A pilot shows how annotators judge; guidelines with examples say what counts.
- **Several annotators.** Assignments, progress, Cohen's κ, Krippendorff's α, and adjudicators for final labels.
- **Exports.** TREC qrels per annotator and by consensus, training pairs, the full action log.

## Quickstart

Needs [Docker](https://docs.docker.com/get-docker/) with Compose, and a terminal: any on Linux or macOS, Git Bash on Windows.

```bash
git clone https://github.com/TIBHannover/CARA.git && cd CARA
bash quickstart.sh --toy
```

- Open <http://localhost:8501>.
- Log in as `admin`; the password is `CARA_ADMIN_PASSWORD` in `.env`, written on the first run.
- `--toy` adds a small dataset of coloured shapes and a study for the annotator `alice` / `alice`.
  Use a private browser window for `alice`.
- `bash quickstart.sh` on its own starts an empty CARA.

### A study on The Met

`bash scripts/met_study.sh` sets up a study on [The Met dataset](http://cmp.felk.cvut.cz/met/) (Ypsilantis et al.,
NeurIPS 2021) in a running CARA. It downloads the dataset from its authors and encodes it, which needs
[uv](https://docs.astral.sh/uv/) and about 4 GB of disk space.

### Stop, restart, update

CARA keeps running in the background after `quickstart.sh` returns. Run these in the CARA folder:

```bash
docker compose stop                   # stop CARA; `docker compose start` resumes it
docker compose down                   # stop and remove the containers; the database stays in a Docker volume
docker compose down -v                # stop and DELETE the database
docker compose up -d --build          # after changing the code: rebuild and restart, keeping the database
```

## Workflow

New study decides how each query's pool is sampled and which encoder groups it. The study's tabs then follow the work.

| Tab | What happens |
|---|---|
| Guidelines | What counts as relevant, with example images. |
| Pilot | A few queries, judged one image at a time, to see how annotators judge. |
| Pilot results | Speed, label shares and agreement of the pilot annotators. |
| Simulation | Compare grouping settings on the pilot's labels or a qrels file. |
| Annotation | Assign the queries (this starts annotation) and adjust the study's settings. |
| Progress | Each annotator's progress. |
| Results | Agreement, final labels, exports. |

Roles per study: admins manage, annotators judge, adjudicators set final labels. Each person has one role.

## Your own data

Put a dataset folder under `data/` (mounted at `/data` in the containers):

```
my_dataset/
  dataset.yaml             name, description (optional)
  images/                  image files; all paths are relative to the folder
  corpus.jsonl             the collection: {"doc_id": ..., "image": ...} per line
  queries/<set>.jsonl      one file per query set, e.g. image.jsonl, text.jsonl
  index/<encoder>/         optional embeddings made elsewhere (corpus.npz, queries-<set>.npz)
  qrels/<set>.qrels        optional sample labels for the simulator
```

A query, with its pool given (candidates in rank order) or built from `corpus.jsonl` by nearest neighbours:

```json
{"query_id": "q1", "image": "images/q1.jpg", "candidates": [{"doc_id": "d7", "image": "images/d7.jpg"}]}
{"query_id": "q2", "text": "a red ceramic vase"}
```

Then add it, and create a study on the Studies page (**New study**):

```bash
docker compose exec backend cara dataset-add /data/my_dataset
```

**Candidate sampling** in New study draws each query's pool, in one of three ways: the candidates listed with the query,
the nearest neighbours of one or more encoders, or a random sample. Embeddings are needed for nearest neighbours and for
grouping, so skip this step only if you use given candidates or a random sample and judge one image at a time:

```bash
docker compose exec backend cara encode my_dataset --encoder siglip2
```

- `encode` needs PyTorch. Build the backend with it once: `docker compose build --build-arg EXTRAS=encode backend`.
- Large encoders such as `dinov3-7b` need a GPU. Embeddings made elsewhere can go in `index/<encoder>/` instead.

## Command line

Run as `docker compose exec backend cara <command>`.

| Command | Does |
|---|---|
| `user-add <name> [--superuser]` | Create an account (password prompted). |
| `dataset-add <folder>` | Register a dataset. |
| `datasets` | List datasets, their query sets and encoders. |
| `encode <dataset> --encoder E` | Embed images and text queries that have no `E` embedding yet. |
| `study-create <settings.yaml> --dataset D` | Create a study from a settings file. |
| `member <study> <name> [--role admin\|adjudicator]` | Add someone to a study (default: annotator). |
| `simulate <study> [--qrels FILE \| --pilot]` | Run the settings simulator. |

## Extending

| To add | Where |
|---|---|
| A Hugging Face encoder | Nothing: `encoder: hf-cls:<model id>` or `hf-dual:<model id>`. |
| An encoder family | A module in `backend/src/cara/encoders/` with an `@register` subclass. |
| A grouping method | A module in `backend/src/cara/grouping/` with an `@register` subclass. |
| Another front end | A client for the API; its schema is at <http://localhost:8000/docs>. |

## Development

```bash
docker compose up -d db
cd backend && uv venv --python 3.12 && uv pip install -e ".[dev]"
set -a && . ../.env && set +a
export CARA_DATABASE_URL=postgresql+psycopg://cara:cara@localhost:5432/cara CARA_IMAGE_ROOT=$PWD/../data
.venv/bin/alembic upgrade head && .venv/bin/fastapi dev
cd ../frontend && uv sync && CARA_API_URL=http://localhost:8000 .venv/bin/streamlit run main.py
```

- Backend checks: `ruff format . && ruff check . && mypy && pytest -q` in `backend/`.
- Frontend checks: `ruff format . && ruff check . && mypy` in `frontend/`.

To reproduce the paper's experiment, run `bash scripts/run_experiments.sh`
([details](https://tibhannover.github.io/CARA/reproducing/)).

## Acknowledgements

The CARA logo is based on a design idea by [Alexsha Maharjan](https://alexshamaharjan.github.io/).

## Citation

If you use CARA, please cite it:

```bibtex
@software{awaleCARA2026,
  author  = {Awale, Sushil and Bitter, Wolfgang and M{\"u}ller-Budack, Eric and Ewerth, Ralph},
  title   = {{CARA}: Cluster-Assisted Relevance Assessment Tool for Image Retrieval Test Collections},
  year    = {2026},
  month   = nov,
  version = {0.1.0},
  doi     = {10.5281/zenodo.23866167},
  url     = {https://github.com/TIBHannover/CARA},
  license = {MIT}
}
```

## Licence

[MIT](LICENSE).
