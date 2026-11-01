# Command line

Run inside the backend container (`docker compose exec backend cara ...`) or locally (see [Development](../development.md)). Every
command runs in one transaction: if it fails, nothing it did is saved, and the error says what to fix.

| Command | Does |
|---|---|
| `cara user-add <name> [--password P] [--superuser]` | create an account; the password is prompted for when not given |
| `cara dataset-add <folder> [--name N] [--path P] [--encoder E]` | register a dataset: images, query sets, embeddings in `index/` (see [Datasets](../setup/datasets.md#adding-a-dataset) for the options) |
| `cara datasets` | list datasets: images, query sets, encoders |
| `cara encode <dataset> --encoder E [--batch-size 64] [--num-workers 4]` | embed the images and text queries that have no `E` embedding yet (needs the `encode` extra; use a GPU for large models; see [Encoding](../setup/encoding.md)) |
| `cara study-create <cara.yaml> --dataset D [--query-set S] [--queries N] [--seed 0] [--member <name>]...` | create a study on a dataset: sample the queries, build the pools, group them, add the annotators |
| `cara load <folder> [--image-dir D] [--member <name>]...` | `dataset-add` and `study-create` for a single-folder study; a dataset of the same name is reused |
| `cara member <study> <name> [--role admin\|annotator\|adjudicator]` | add someone to a study, or change their role |
| `cara pilot <study> --count N [--seed 0]` | choose pilot queries (assign them to annotators in the study's Pilot tab) |
| `cara pilot <study> --count N --labels QRELS --annotator NAME [--then NAME...]` | record a pilot from known labels (drawn from the queries in the file); `--then` assigns the other queries to the real study's annotators |
| `cara judge <study> --labels QRELS --annotator NAME [--first N]` | record a user's judgments of their first N queries from known labels (demos, tests) |
| `cara simulate <study> [--qrels FILE \| --pilot] [--max-queries 30]` | the settings simulator, with common settings and the typical annotator; prints a table |
| `cara build-pools <study>`, `cara cluster <study>` | rebuild a study's pools or groups (before judging starts) |
