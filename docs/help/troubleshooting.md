# Troubleshooting

Common problems, by where they show up. Every `cara` command reports an error as one line that says what is wrong
and, where it can, how to fix it. If yours isn't covered here, please
[open an issue](https://github.com/TIBHannover/CARA/issues) with the command and its output.

## Starting CARA

**`set CARA_SECRET_KEY in .env`**
:   `.env` is missing or has no secret key. `bash quickstart.sh` writes one; by hand, copy `.env.example` to `.env`
    and set `CARA_SECRET_KEY` to the output of `openssl rand -hex 32`.

**`port is already allocated`**
:   Another program uses port 8501, 8000 or 5432, often a second copy of CARA. Stop it, or change the left-hand
    port under `ports:` in `compose.yaml`.

**Everyone is logged out**
:   Logins last `CARA_TOKEN_MINUTES` (12 hours by default), and changing `CARA_SECRET_KEY` ends them all. Logging in
    again is enough.

## Encoding

**`cara encode: needs the encode extra (torch is missing)`**
:   The default Docker image leaves PyTorch out. Build the backend with it, with or without a GPU
    ([Where to encode](../setup/encoding.md#where-to-encode)).

**`torch.cuda.is_available()` prints `False` in Docker**
:   The container doesn't see the GPU. Check that `nvidia-smi` works on the host, that the NVIDIA Container Toolkit
    is installed, and that `compose.gpu.yaml` was passed to `docker compose up`.

**`401` or `403` while downloading a model**
:   The model is gated, as DINOv3 is. Accept its licence on its Hugging Face page, put `HF_TOKEN` in `.env`, and
    restart the backend with `docker compose up -d`.

**`unable to allocate shared memory`**
:   The processes that load images exchange them through shared memory. Inside Docker, `compose.yaml` gives the
    backend enough; elsewhere, run with `--num-workers 0`.

**Out of GPU memory**
:   Lower `--batch-size`, for example to 16.

## Creating a study

**An encoder or a sampling method is missing on the New study page**
:   An encoder is offered for nearest neighbours only once it has embedded the set's queries. **Show embeddings** under
    **Candidate sampling** lists what each encoder covers and the `cara encode` command for what is missing.

**Nearest neighbours isn't offered for composed queries**
:   `cara encode` can't embed a query made of an image and a text. Give the queries candidates in their query file,
    or an embedding from your composed retrieval method ([What gets encoded](../setup/encoding.md#what-gets-encoded)).

## During a study

**A setting can't be changed: it is locked**
:   The first judgment of an annotation query fixes the pools, the grouping and the review rules, so that every
    judgment is comparable ([What the first judgment locks](../study/annotation.md#settings)). To try
    other settings, create a new study on the same dataset.

**An annotator sees no queries**
:   Once pilot queries are chosen, annotators see only the queries assigned to them. Assign them pilot queries in
    the **Pilot** tab, or start annotation in the **Annotation** tab.

**The pages are slow with many annotators**
:   The web app runs every browser session in one process. See [Capacity](../setup/deployment.md#capacity).
