# Release notes

CARA follows [semantic versioning](https://semver.org/). Upgrading is described in
[Deployment](../setup/deployment.md#upgrading).

## 0.1.0 (1 November 2026)

The first public release, archived as [10.5281/zenodo.23866167](https://doi.org/10.5281/zenodo.23866167).

- **Judging:** groups of similar images with a label bar, labels per image, splitting a group, a review round sorted
  by label, and an optional Suggest mode. Image, text and composed (image and text) queries.
- **Pools:** given candidates, the nearest neighbours of one or more encoders, each to its own depth, or a random
  sample.
- **Grouping:** agglomerative clustering, k-means and HDBSCAN, with a cap on group size; new methods are one
  module each.
- **Encoders:** DINOv3, CLIP, SigLIP 2 and any Hugging Face image or text–image model; new encoders are one module
  each.
- **Study workflow:** pilot with speed and agreement measures, annotation guidelines with examples, a settings
  simulator that compares groupings in time and recall, and assignments for several annotators.
- **Results:** Cohen's κ and Krippendorff's α, adjudication, and exports of TREC qrels (per annotator and by
  consensus), training pairs and the action log.
- **Running it:** Docker Compose, with an optional GPU override for encoding and a toy dataset. A script
  downloads The Met from its authors and prepares a study.
