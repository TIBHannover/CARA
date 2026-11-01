# Encoding

CARA uses embeddings to group images, and for one of its [candidate sampling](../study/new-study.md#3-candidate-sampling)
methods, nearest neighbours. `cara encode` embeds whatever a dataset doesn't have an embedding for yet, with the encoder
you name.

You can skip this page if your study uses given candidates or a random sample and judges one image at a time
([From a dataset to pools](../study/index.md#from-a-dataset-to-pools)).

!!! info "Before you begin"
    The dataset is added ([Datasets](datasets.md)). Embeddings you made elsewhere need no encoding: put them in
    the dataset's `index/` folder instead.

## What gets encoded

```bash
docker compose exec backend cara encode my_dataset --encoder clip
```

| Input | Encoded |
|---|---|
| Images (corpus, candidates and query images) | every image without an embedding for that encoder |
| Text queries | when the encoder reads text (`clip`, `siglip2`, `hf-dual:`) |
| Composed queries (image and text) | never: give them candidates in their query file, or an embedding from your composed retrieval method in `index/<encoder>/queries-<set>.npz` |

Only what is missing is encoded, so the command can run again, for example after you add images.

| Option | Default | Meaning |
|---|---|---|
| `--encoder` | required | The encoder, as listed below. |
| `--batch-size` | `64` | Images per batch; lower it if the GPU runs out of memory. |
| `--num-workers` | `4` | Processes that load images; `0` loads them in the main process. |

**Show embeddings** in [Candidate sampling](../study/new-study.md#3-candidate-sampling) shows how many images each
encoder covers and which query sets it is ready for.

## Choosing an encoder

| Encoder | Model | Reads | Runs on |
|---|---|---|---|
| `clip` | CLIP ViT-B/16 | images and text | a CPU is enough |
| `dinov3` | DINOv3 ViT-B/16 | images | a CPU is enough |
| `dinov3-7b` | DINOv3 ViT-7B/16 | images | a large GPU |
| `siglip2` | SigLIP 2 giant, 384 px | images and text | a GPU |
| `hf-cls:<model id>` | any Hugging Face image encoder whose CLS token is the embedding (DINO-style) | images | depends on the model |
| `hf-dual:<model id>` | any Hugging Face text–image encoder (CLIP-style) | images and text | depends on the model |

A named encoder also takes another checkpoint, as `<name>:<model id>`, such as
`siglip2:google/siglip2-base-patch16-224`. The full name is how the dataset stores the embeddings, so a study
uses exactly the name `cara encode` used. A new encoder is one small module ([Extending CARA](../reference/extending.md)).

!!! tip "Several encoders"
    A dataset can hold the embeddings of several encoders. A study then samples nearest neighbours from any of them, each to its own
    depth, which keeps the pool from favouring what one encoder finds.

## Where to encode

CARA uses an NVIDIA GPU whenever PyTorch finds one, and the CPU otherwise, as on a Mac. On a CPU, `clip` embeds about 350 images a
minute on 12 cores. The default Docker image leaves PyTorch out to stay small, so choose one of these options:

| Option | When | You need |
|---|---|---|
| [A · Docker with an NVIDIA GPU](#a-docker-with-an-nvidia-gpu) | CARA runs on a machine with an NVIDIA GPU | the NVIDIA driver and the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) |
| [B · Docker, CPU only](#b-docker-cpu-only) | small encoders and collections: `clip` takes about half an hour for 10,000 images | nothing extra |
| [C · Another machine](#c-another-machine) | the GPU is on a different machine | Python with [uv](https://docs.astral.sh/uv/), the dataset's images, and access to CARA's database |
| [D · Embeddings made elsewhere](datasets.md#embeddings-made-elsewhere) | you already have embeddings | nothing: put them in `index/<encoder>/` |

### A · Docker with an NVIDIA GPU

```bash
docker compose -f compose.yaml -f compose.gpu.yaml up -d --build
docker compose exec backend python -c "import torch; print(torch.cuda.is_available())"   # True
docker compose exec backend cara encode my_dataset --encoder dinov3-7b
```

`compose.gpu.yaml` builds the backend with PyTorch and gives it the GPU. The first build downloads PyTorch
(several GB).

!!! warning
    Pass both files to every later `docker compose up`, or the backend goes back to the image without PyTorch.

### B · Docker, CPU only

```bash
docker compose build --build-arg EXTRAS=encode backend && docker compose up -d
docker compose exec backend cara encode my_dataset --encoder clip
```

### C · Another machine

Run `cara encode` from a clone of CARA on the GPU machine. It reads the same images and writes the embeddings
straight into CARA's database:

```bash
ssh -N -L 5432:localhost:5432 <cara host> &      # the database listens on the CARA machine only
cd backend && uv sync --extra encode
export CARA_DATABASE_URL=postgresql+psycopg://cara:<password>@localhost:5432/cara
export CARA_IMAGE_ROOT=/path/to/data              # the folder that holds my_dataset/, as data/ does for CARA
uv run cara encode my_dataset --encoder dinov3-7b
```

`<password>` is `POSTGRES_PASSWORD` from CARA's `.env` (`cara` if it is empty).

## Models and access tokens

Models are downloaded on first use and kept in the `hf-cache` Docker volume. Gated models, such as DINOv3, need
their licence accepted on their Hugging Face page and an access token in `.env`:

```bash
HF_TOKEN=hf_...
```

!!! note
    Publications that use DINOv3 must acknowledge it, as its licence requires.
