# Installation

CARA runs as three services: Postgres with pgvector, the API (FastAPI) and the web app (Streamlit). Docker
Compose starts all three on one machine.

!!! info "Before you begin"
    - [Docker](https://docs.docker.com/get-docker/) with Compose, on [your system](#your-system).
    - A GPU only if you will embed a large image collection yourself; see [Encoding](../setup/encoding.md).

## Your system

CARA runs in Docker, so it needs no other installation. Its setup scripts are bash, which you run in a terminal:

| System | Install | Run the commands in |
|---|---|---|
| Linux | Docker with Compose | any terminal |
| macOS | Docker Desktop | Terminal |
| Windows | Docker Desktop and Git for Windows | Git Bash, which comes with Git for Windows |

## Quick start

```bash
git clone https://github.com/TIBHannover/CARA.git && cd CARA
bash quickstart.sh --toy
```

Open <http://localhost:8501> and log in as `admin`. On its first run the script writes `.env` with a generated
admin password (`CARA_ADMIN_PASSWORD`); the API creates that account when the database has no users yet.

| Command | Starts with |
|---|---|
| `bash quickstart.sh` | an empty database |
| `bash quickstart.sh --toy` | a small synthetic dataset and study, with the annotator `alice` (password `alice`) |

!!! tip
    The [tutorial](tutorial.md) walks through a whole study on the toy data in about ten minutes.

## A study on The Met

To try CARA on museum images, this script sets up a study on
[The Met dataset](http://cmp.felk.cvut.cz/met/). It downloads the dataset from its authors and encodes it:

```bash
bash quickstart.sh
bash scripts/met_study.sh
```

It needs [uv](https://docs.astral.sh/uv/) and about 4 GB of disk space. The authors' server can be slow; if the download
stops, run the script again and it resumes. By default it encodes 5,000 images of the mini Met database with CLIP, which
takes about 15 minutes on a CPU, and creates a study of 10 queries with pools of 50. Encoding on the machine itself needs
an Apple silicon Mac on macOS.
Use `--encoder`, `--queries`, `--pool-size` and `--max-images` to change these; `--max-images 0` encodes all the images.
The Met's images and photos keep their own licences; see the [dataset's page](http://cmp.felk.cvut.cz/met/).

## What runs where

| Service | Address | Notes |
|---|---|---|
| Web app | <http://localhost:8501> | what admins and annotators open |
| API | <http://localhost:8000> | reachable from the machine itself only; interactive schema at `/docs` |
| Postgres | `localhost:5432` | reachable from the machine itself only; data in the `pgdata` volume |

## Stopping and starting

```bash
docker compose stop          # stop; data stays
docker compose up -d         # start again
docker compose down -v       # remove everything, including the database
```

Datasets are added on the command line ([Datasets](../setup/datasets.md)); everything else happens in the web
app. To serve CARA to a team, see [Deployment](../setup/deployment.md).
