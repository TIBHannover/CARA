# Study settings

A study's settings, as `cara study-create` and `cara load` read them from a YAML file. The New study page fills
them in for you, and admins can change them later in the study's *Annotation* tab.

Every key is checked when the file is read: a typo or an unknown key is an error, not ignored, and the message
names the file and every field at fault.

## A complete example

Only `name`, `encoder` and `labels` are required; every other value below is the default.

```yaml
name: My collection
encoder: dinov3
labels:
  - {name: Relevant, short: "✓", grade: 1, colour: "#2ecc71"}
  - {name: Not Relevant, short: "✗", grade: 0, colour: "#e74c3c"}
  - {name: Unsure, short: "?", grade: null, colour: "#f1c40f"}
pool: {source: knn, k: 200, max_size: 1000}
grouping: {method: agglomerative, linkage: average, max_size: 16}
solo: {percentile: 10}
top_k_individual: 0
order: similarity
query_order: shuffled
review: {enabled: true, required: false, negatives_shown: 60}
annotators_per_query: 1
display: {thumb_px: 320, query_px: 640, cols: 5, drag_and_drop: true, split: true, group_order: similarity}
suggest: {enabled: false, min_seeds: 2, min_pool_size: 0, min_margin: 0.05, merge_percentile: 50}
demo: false
```

## The study

| Key | Default | Meaning |
|---|---|---|
| `name` | required | Shown everywhere; must be unique among studies. |
| `encoder` | required | The encoder whose embeddings build the pools (for `knn`) and group them: `clip`, `dinov3`, `siglip2`, or `<name>:<model id>` (see [Encoding](../setup/encoding.md)). The dataset must have its embeddings. |
| `top_k_individual` | `0` | How many of the images most similar to the query stay ungrouped. |
| `order` | `similarity` | How images are ranked: by similarity to the query, or `pool_rank`, the pool's own order (for queries without an embedding of their own). |
| `query_order` | `shuffled` | `shuffled`: each annotator gets the queries in their own fixed random order, which avoids order effects; `listed`: everyone in the order of the query file. |
| `annotators_per_query` | `1` | How many annotators judge each annotation query. |
| `demo` | `false` | A sample study to try the tool on, listed apart below the real studies. |

## Labels

At least two, with unique names.

| Key | Default | Meaning |
|---|---|---|
| `name` | required | What annotators click. |
| `grade` | required | The relevance written to the qrels. Every grade of 1 or more counts as relevant in CARA (review order, Suggest mode, the simulator). `null`: counts as judged but is left out of the qrels (Unsure). |
| `colour` | required | The button and border colour, such as `"#2ecc71"`. |
| `short` | the name | A shorter form, where space is tight (the Disagreements view). |
| `icon` | from the grade | A [Material Symbols](https://fonts.google.com/icons) name, such as `check`, `close` or `help`. |
| `offered` | `true` | Whether annotators can choose it. Only a label without a grade can be switched off; images that already have it keep it. |

Graded relevance: give the labels grades 2, 1 and 0 (for example Highly Relevant, Relevant, Not Relevant); the
qrels carry the grade.

## Candidate sampling: `pool`

How each query's pool is sampled from the collection.

| Key | Default | Meaning |
|---|---|---|
| `source` | `knn` | `knn`: the query's nearest neighbours in the corpus; `file`: the candidates in the query file; `random`: `k` images drawn at random per query, a baseline. |
| `k` | `200` | How many images each pool takes; see below the table. |
| `depths` | `{}` | `knn` only: the pooling encoders and how many nearest images each contributes, e.g. `{dinov3: 30, clip: 20}`. The pool is their union, each image once, so it holds up to the sum (TREC-style depth pooling). |
| `max_size` | `1000` | The most images a pool can hold; the depths must not add up to more. |
| `seed` | `0` | `random` only: the seed of the draws; each query draws from it and its own id. |

The meaning of `k` depends on the source:

- `knn`: the depth of the study's own encoder when `depths` is empty. `null` means the whole corpus, up to `max_size`.
- `random`: the number of images drawn per query.
- `file`: must be `null`.

## Grouping: `grouping`

`method` picks the grouping method; each has its own keys. Every method that makes groups also takes
`max_size` (default `16`): larger groups are split in two until they fit.

| `method` | Keys (defaults) | Groups |
|---|---|---|
| `agglomerative` | `linkage: average` (or `complete`, `single`) | a tree of similar images, cut so no group is larger than `max_size`; `linkage` also splits groups in two |
| `kmeans` | `n_groups: 12`, `seed: 0` | a fixed number of clusters per pool |
| `hdbscan` | `min_cluster_size: 3` | dense clusters only; the other images stay ungrouped |
| `none` | | no groups: every image is ungrouped |

A new method is one module in `backend/src/cara/grouping/` (see [Extending CARA](extending.md)).

## Ungrouped images: `solo`

| Key | Default | Meaning |
|---|---|---|
| `percentile` | `10` | An image whose nearest neighbour is less similar than this percentile of the pool's nearest-neighbour similarities stays ungrouped, because it would make a group mixed. `0` turns the rule off. |

## Review: `review`

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | A review round after a pool is labelled. |
| `required` | `false` | Whether a query counts as done only after its review. |
| `negatives_shown` | `60` | How many Not Relevant images the review shows, those most like the Relevant ones first. |

## The judge page: `display`

Each annotator can change the images per row for themselves.

| Key | Default | Meaning |
|---|---|---|
| `thumb_px` | `320` | Thumbnail size in pixels (at least 64). |
| `query_px` | `640` | Query image size in pixels (at least 64). |
| `cols` | `5` | Images per row, 1 to 12. |
| `drag_and_drop` | `true` | Whether review mode lets annotators drag an image to another label; the buttons work either way. |
| `split` | `true` | Whether annotators may split a group in two, and undo it. |
| `group_order` | `similarity` | The order of the groups: `similarity` or `size`, descending; `similarity_asc` or `size_asc`, ascending. |

## Suggest mode: `suggest`

Once an annotator has marked enough images Not Relevant one by one (the seeds), every unjudged image clearly
similar to a seed gets that seed's label as a suggestion, to accept or override.

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `false` | Offer Suggest mode. |
| `min_seeds` | `2` | Not Relevant seeds needed before suggestions start; Relevant seeds are optional. |
| `min_pool_size` | `0` | Offer it only for pools at least this large (deep pools, whole-corpus studies); `0`: every pool. |
| `min_margin` | `0.05` | How much more similar (cosine) an image must be to its seed than to any image of the other label. |
| `merge_percentile` | `50` | Seeds with the same label count as one if they are at least as similar as this percentile of the pool's nearest-neighbour pairs (50: a typical nearest neighbour; 100: never merge). |

## What locks when judging starts

The first judgment of an annotation query (not a pilot query) locks the study, so every judgment in it is
comparable. After that only these can change:

- `name`, `annotators_per_query`, `query_order`, `demo`, `display` and `suggest`;
- the labels' colours, short names and icons.

Label names and grades can't change at all once the study exists, before or after the lock: judgments refer to
them.

Changing anything else is refused with the list of locked settings it touches. Before that, changing the grouping
or the pool size in the *Annotation* tab regroups or rebuilds the pools straight away.

## The server's settings

How the API itself runs (database, image folder, login tokens) is set by `CARA_*` environment variables in `.env`,
not per study; see [Deployment](../setup/deployment.md#server-settings).
