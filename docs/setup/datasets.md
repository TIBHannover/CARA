# Datasets

A **dataset** holds the images and one or more query sets, and optionally embeddings. Several [studies](../study/index.md)
can share one dataset; each judges one of its query sets, whole or as a random sample. Datasets are added on the
command line by whoever runs the server.

!!! info "Before you begin"
    CARA is running ([Installation](../get-started/installation.md)), and your files are under `data/`, which the
    containers see as `/data`.

## Folder layout

```text
my_dataset/
  dataset.yaml             name and description (optional; the name defaults to the folder name)
  images/                  the image files; every path below is relative to my_dataset/
  corpus.jsonl             the collection to retrieve from, one {"doc_id": ..., "image": ...} per line
  queries/<set>.jsonl      one file per query set, such as image.jsonl, text.jsonl, composed.jsonl
  index/<encoder>/         optional: embeddings made elsewhere
    corpus.npz             ids (image paths, of corpus and query images) and emb_nd
    queries-<set>.npz      ids (query ids) and emb_nd, for text or composed queries
  qrels/<set>.qrels        optional: sample labels, which the settings simulator offers
```

`dataset.yaml` has two keys:

```yaml
name: The Met (demo subset)
description: Photographs of objects, with image, text and composed queries.
```

## Query files

A query file has one query per line: an image, a text, or both (a composed query).

```json
{"query_id": "q1", "image": "images/q1.jpg", "candidates": [{"doc_id": "d7", "image": "images/d7.jpg"}]}
{"query_id": "q2", "text": "a red ceramic vase"}
{"query_id": "q3", "image": "images/q3.jpg", "text": "the same, but in bronze", "candidates": [...]}
```

| Key | Required | Meaning |
|---|---|---|
| `query_id` | yes | Unique within the file. |
| `image`, `text` | at least one | The query: an image path, a text, or both. |
| `candidates` | no | The query's pool, in rank order, such as the pool of existing runs. Without it, CARA samples the pool from the corpus ([Candidate sampling](../study/new-study.md#3-candidate-sampling)). |

Images are found by path, so an image used by several query sets, or as both a query and a candidate, is stored
once.

## Embeddings made elsewhere

Each `index/<encoder>/` folder holds one encoder's embeddings, under the name studies will use for it: `dinov3`,
`clip`, or your own name for your own model. Each `.npz` file has two arrays of the same length:

| Array | Holds |
|---|---|
| `ids` | image paths (in `corpus.npz`) or query ids (in `queries-<set>.npz`) |
| `emb_nd` | one embedding per id, in the same order |

CARA scales every embedding to unit length, so a dot product is the cosine similarity. Ids the dataset doesn't
have are skipped, and the log says how many images are still without an embedding. An all-zero row is refused,
since it has no direction to compare.

Without embeddings of your own, [encode](encoding.md) the dataset after adding it, if your study
[needs them](../study/index.md#from-a-dataset-to-pools).

## Adding a dataset

```bash
docker compose exec backend cara dataset-add /data/my_dataset
docker compose exec backend cara datasets      # images, query sets and encoders of every dataset
```

| Option | Default | Meaning |
|---|---|---|
| `--name` | the name in `dataset.yaml`, else the folder name | The dataset's name; unique. |
| `--path` | the folder name | The image folder, relative to `/data`. |
| `--encoder` | none | The encoder that made a single `embeddings.npz` (the single-folder layout below). |

The command runs in one transaction: if a file is wrong, nothing is added. The error names the file and, for a
query or corpus file, the line, so you can fix it and run the command again. It also reports repeated query ids,
and an `.npz` file without `ids` or `emb_nd` or with arrays of different lengths.

??? note "The single-folder layout"
    `cara load <folder>` loads a folder with `cara.yaml`, `queries.jsonl`, `images/`, `embeddings.npz` (made with
    the encoder named in `cara.yaml`) and, for nearest-neighbour pools, `corpus.jsonl`, as a dataset and a study
    in one step. A dataset of the same name is reused, so the folder loads again as a second study when
    `cara.yaml` names another study.
