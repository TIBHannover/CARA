# Reproducing the paper

These scripts reproduce the use case in the CARA paper. They download [The Met dataset](http://cmp.felk.cvut.cz/met/)
from its authors, build three query sets from its test split, simulate judging them, and write the paper's table.

!!! info "Before you begin"
    - [uv](https://docs.astral.sh/uv/), on [any supported system](get-started/installation.md#your-system).
    - An NVIDIA GPU: building the datasets embeds about 397,000 images.
    - More than 28 GB of disk space for the download, plus the datasets and embeddings.
    - Access to DINOv3: accept its licence on its Hugging Face page and set `HF_TOKEN` in `.env`.

## What is simulated

| Query set | Queries | Relevant images | Pool of 100 from |
|---|---|---|---|
| Image | 1,003 | Photos of the same exhibit | DINOv3 |
| Text | 232 | Same object type | SigLIP 2 |
| Image + text | 767 | Same object type as the photo, from the culture the text names | SigLIP 2 |

Groups come from the DINOv3 embeddings. Each query set is judged under 43 grouping settings and one image at a time, by
the Typical annotator type with a review round, and by Perfect and Group-only as bounds
([Simulated annotators](study/simulation.md#simulated-annotators)).

## Run it

```bash
bash scripts/run_experiments.sh
```

It runs these steps in order. Each is also a script of its own:

| Step | Script | Writes |
|---|---|---|
| 1. Download The Met | `scripts/download_met.sh` | `data/met_source/` |
| 2. Build the datasets | `scripts/build_datasets.sh` | `data/met_test_all/`, `data/met_text_test/`, `data/met_composed_test/` |
| 3. Simulate | `scripts/simulate.sh` | `outputs/paper/<dataset>/` |
| 4. Analyse and write the table | `scripts/analyze.sh` | `outputs/paper_analysis/` |

We built the datasets on one GPU with 16 CPU cores and 96 GB of memory. The simulations need no GPU: we used 16 cores
and 32 GB, on which the image query set takes about 2 hours and the others less. Embeddings are cached, so running the
build again takes minutes. To resume an interrupted download, run its script again.

## Expected results

`outputs/paper_analysis/table.md` holds the paper's table, for the Typical annotator type. Time saved and the change in
recall, in points, are relative to judging one image at a time. A16·10% means agglomerative groups of at most 16 images
with 10% of the images ungrouped, and K10 means k-means with 10 groups.

| Query set | Queries | Relevant per pool | Recall, one at a time | Default A16·10%: saved | Δ recall | Recommended | Saved | Δ recall |
|---|---|---|---|---|---|---|---|---|
| Image | 1,003 | 3% | 0.68 | 72% | −0.9 | A16·0% | 78% | −1.2 |
| Text | 232 | 15% | 0.67 | 66% | −0.8 | K10 | 78% | +0.2 |
| Image + text | 767 | 1% | 0.69 | 72% | −3.8 | A32·0% | 82% | −1.1 |

`summary.csv` in the same folder has every setting and annotator type.

## Options

Set these in the environment or in `.env`.

| Variable | Default | Meaning |
|---|---|---|
| `MET_ROOT` | `data/met_source` | Where The Met is downloaded. |
| `MET_OBJECTS` | `data/MetObjects.csv` | The Met's Open Access metadata; downloaded when missing. |
| `DATA` | `data` | Where the datasets are built. |
| `CACHE_DIR` | `outputs/cache` | Where the embeddings are cached. |
| `BATCH_SIZE` | `128` | Images per batch when encoding. |
| `LOADERS` | 4 on Linux, otherwise 0 | Processes that load images. |
| `WORKERS` | the number of CPU cores | Processes that simulate. |
| `SKIP_PREPARE` | unset | Skips steps 1 and 2 in `run_experiments.sh`. |

## Data

[The Met dataset](http://cmp.felk.cvut.cz/met/) (Ypsilantis et al., NeurIPS 2021): the studio images are CC0, and the
visitor photos are by the dataset's authors or under Flickr Creative Commons licences. The object types and cultures come
from the [Met Open Access metadata](https://github.com/metmuseum/openaccess) (CC0).
