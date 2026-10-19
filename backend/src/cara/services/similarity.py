"""Images like the ones an annotator chose: a query's similar images, and Suggest mode's suggestions."""

from dataclasses import dataclass, replace

import numpy as np

from cara.core.suggest import merge_threshold
from cara.core.suggest import suggest as core_suggest
from cara.db.models import Source, UserRow
from cara.errors import Forbidden, NotFound
from cara.repositories.database import Database
from cara.services.studies import StudyService, encoder_of, settings_of


@dataclass(frozen=True, slots=True)
class SuggestedCluster:
    """Unjudged images most like images the annotator marked, with the marked images' label suggested.

    The marked images (`seeds`) are one image or several near-identical ones. `seeds` is empty and `label`
    None for the images that get no suggestion.
    """

    seeds: list[int]
    label: str | None
    members: list[int]


@dataclass(frozen=True, slots=True)
class Suggestions:
    """Suggest mode's state for one query and annotator.

    Attributes:
        ready: Whether enough images are marked Not Relevant one by one for suggestions to start.
    """

    ready: bool
    relevant_seeds: int
    nonrelevant_seeds: int
    min_seeds: int
    clusters: list[SuggestedCluster]


class SimilarityService:
    """Nearest neighbours within a query's pool. Every method checks that the annotator may see the query."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.studies = StudyService(db)

    def similar(self, user: UserRow, study_id: int, query_id: int, to: list[int], k: int) -> list[int]:
        """Return the `k` pool images most like any of `to`, most similar first.

        One image: its nearest neighbours in the pool. Several (say, every image labelled Relevant): the
        images that look most like one of them, which is where a missed Relevant image is likely to be.

        Raises:
            NotFound: Some of `to` aren't in the query's pool.
        """
        settings = settings_of(self.studies.get(study_id))
        _, pool = self.studies.pool_for(user, study_id, query_id)
        members = sorted(pool.members, key=lambda m: m.rank)
        index = {m.id: i for i, m in enumerate(members)}
        unknown = sorted(set(to) - index.keys())
        if unknown or not to:
            raise NotFound(f"members {unknown} are not in the pool of query {query_id}")
        encoder = encoder_of(settings, "Similar images")
        emb_nd = self.db.datasets.embeddings(encoder, [m.image_id for m in members])
        score_n = (emb_nd @ emb_nd[[index[m] for m in to]].T).max(axis=1)
        score_n[[index[m] for m in to]] = -np.inf
        return [
            members[i].id for i in np.argsort(-score_n, kind="stable")[: min(k, len(members) - len(set(to)))]
        ]

    def suggestions(self, user: UserRow, study_id: int, query_id: int) -> Suggestions:
        """Return Suggest mode's suggestions for the annotator, by `core.suggest`'s rule.

        Marked images are the annotator's labels set one by one (image buttons or review); Unsure marks
        nothing. Suggestions start with `min_seeds` Not Relevant marks; Relevant ones are optional, because a
        pool may hold one Relevant image or none. The query image counts as Relevant; text queries, and
        composed queries whose image was never embedded, have no image to compare with.

        Raises:
            Forbidden: Suggest mode is off, or the query is a pilot query.
        """
        study = self.studies.get(study_id)
        settings = settings_of(study)
        query, pool = self.studies.pool_for(user, study_id, query_id)
        if not settings.suggest.enabled or query.is_pilot:
            raise Forbidden("suggestions are off for this query")
        grade = {row.name: row.grade for row in study.labels}
        labels = self.db.judgments.labels_in_pool(user.id, pool.id)
        members = sorted(pool.members, key=lambda m: m.rank)
        seeds = [
            (i, label)
            for i, m in enumerate(members)
            if (label := labels.get(m.id, (None, None))[0]) is not None
            and labels[m.id][1] in {Source.ITEM, Source.REVIEW}
            and grade.get(label) is not None
        ]
        positive_s = np.array([(grade[label] or 0) >= 1 for _, label in seeds], dtype=bool)
        needed = settings.suggest.min_seeds
        ready = int((~positive_s).sum()) >= needed
        result = Suggestions(ready, int(positive_s.sum()), int((~positive_s).sum()), needed, [])
        open_ = [i for i, m in enumerate(members) if m.id not in labels]
        if not ready or not open_:
            return result
        encoder = encoder_of(settings, "Suggest mode")
        emb_nd = self.db.datasets.embeddings(encoder, [m.image_id for m in members])
        sim_nn = emb_nd @ emb_nd.T
        seed_rows = [i for i, _ in seeds]
        query_o = None
        if query.image_id is not None and (
            query.image_id,
            encoder,
        ) in self.db.datasets.image_encoders([query.image_id]):
            query_o = emb_nd[open_] @ self.db.datasets.embeddings(encoder, [query.image_id])[0]
        found, rest = core_suggest(
            sim_nn[np.ix_(open_, seed_rows)],
            sim_nn[np.ix_(seed_rows, seed_rows)],
            positive_s,
            query_o,
            settings.suggest.min_margin,
            merge_threshold(sim_nn, settings.suggest.merge_percentile),
        )
        clusters = [
            SuggestedCluster(
                [members[seed_rows[k]].id for k in s.seeds],
                seeds[s.seeds[0]][1],
                [members[open_[o]].id for o in s.members],
            )
            for s in found
        ]
        if rest:
            clusters.append(SuggestedCluster([], None, [members[open_[o]].id for o in rest]))
        return replace(result, clusters=clusters)
