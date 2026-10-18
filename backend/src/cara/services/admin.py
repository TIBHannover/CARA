"""What a study's admins see and do: progress, agreement, adjudication, exports, members and assignments."""

import json
from collections import Counter
from dataclasses import dataclass
from itertools import cycle
from statistics import median
from typing import Literal

from cara.core.agreement import LabelsByUser, alpha, disagreements, pairwise_kappa
from cara.core.export import consensus, qrels_lines, training_pairs
from cara.core.pilot import IDLE_SECONDS
from cara.db.models import Role, UserRow
from cara.errors import Conflict, Invalid, NotFound
from cara.repositories.database import Database
from cara.repositories.judgments import JudgmentRecord
from cara.services.studies import StudyService, settings_of
from cara.services.users import UserService

Export = Literal["qrels", "consensus_qrels", "pairs", "actions"]
"""The exports: one annotator's qrels, consensus qrels, training pairs, and the action log."""


@dataclass(frozen=True, slots=True)
class ProgressRow:
    """One member's progress in a study.

    Attributes:
        queries: The queries they may see.
        complete: Of those, the ones with every image labelled.
        median_seconds_per_action: The median gap between their actions, breaks left out.
        active_minutes: The gaps between their actions summed, breaks over `IDLE_SECONDS` left out.
    """

    username: str
    role: Role
    queries: int
    complete: int
    reviewed: int
    judgments: int
    median_seconds_per_action: float | None
    active_minutes: float


@dataclass(frozen=True, slots=True)
class PairAgreement:
    """Cohen's kappa between two annotators, over the images both labelled."""

    annotator_a: str
    annotator_b: str
    shared_items: int
    kappa: float | None


@dataclass(frozen=True, slots=True)
class QueryAgreement:
    """Agreement within one query.

    How many annotators, how many images they disagree on, how many of those an admin has decided, and
    Krippendorff's alpha.
    """

    query_id: int
    external_id: str
    annotators: int
    disagreements: int
    adjudicated: int
    alpha: float | None


@dataclass(frozen=True, slots=True)
class AgreementReport:
    """A study's agreement: alpha over every image with two or more labels, kappa per pair, and per query.

    Attributes:
        label_counts: Every judgment, counted by label.
    """

    alpha: float | None
    items_with_two_or_more: int
    label_counts: dict[str, int]
    pairs: list[PairAgreement]
    queries: list[QueryAgreement]


@dataclass(frozen=True, slots=True)
class DisagreementItem:
    """One pool image the annotators disagree on, with each one's label and the adjudicated label, if any."""

    member_id: int
    image_id: int
    doc_id: str
    labels: dict[str, str]
    adjudicated: str | None


@dataclass(frozen=True, slots=True)
class Member:
    """A member of a study, with their role and how many queries are assigned to them."""

    username: str
    role: Role
    assigned: int


def _labels_by_user(records: list[JudgmentRecord]) -> LabelsByUser:
    by_user: LabelsByUser = {}
    for r in records:
        by_user.setdefault(r.username, {})[(r.query_external_id, r.doc_id)] = r.label
    return by_user


def _labels_by_query(records: list[JudgmentRecord]) -> dict[str, dict[str, str]]:
    by_query: dict[str, dict[str, str]] = {}
    for r in records:
        by_query.setdefault(r.query_external_id, {})[r.doc_id] = r.label
    return by_query


def _gaps(times: list[float]) -> list[float]:
    return [b - a for a, b in zip(times, times[1:], strict=False) if 0 < b - a <= IDLE_SECONDS]


class AdminService:
    """A study admin's view and actions."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.studies = StudyService(db)
        self.users = UserService(db)

    def progress(self, study_id: int) -> list[ProgressRow]:
        """Return each member's progress in the study.

        Raises:
            NotFound: The study doesn't exist.
        """
        self.studies.get(study_id)
        all_pools = self.db.studies.list_pools(study_id)
        records = self.db.judgments.in_study(study_id)
        times = self.db.judgments.action_times(study_id)
        rows = []
        for username, role in self.db.users.members(study_id):
            user = self.users.get(username)
            visible = self.studies.visible_queries(user.id, study_id)
            mine = [p for p in all_pools if visible is None or p.query_id in visible]
            judged = Counter(r.query_id for r in records if r.username == username)
            reviewed = self.db.judgments.reviewed_queries(user.id, study_id)
            mine_times = [t.timestamp() for t in times.get(username, [])]
            gaps = _gaps(mine_times)
            rows.append(
                ProgressRow(
                    username=username,
                    role=role,
                    queries=len(mine),
                    complete=sum(judged[p.query_id] == len(p.members) for p in mine),
                    reviewed=sum(p.query_id in reviewed for p in mine),
                    judgments=sum(judged.values()),
                    median_seconds_per_action=median(gaps) if gaps else None,
                    active_minutes=sum(gaps) / 60,
                )
            )
        return rows

    def agreement(self, study_id: int) -> AgreementReport:
        """Measure agreement in the study: overall, per pair of annotators, and per query.

        Raises:
            NotFound: The study doesn't exist.
        """
        settings = settings_of(self.studies.get(study_id))
        label_names = [label.name for label in settings.labels]
        records = self.db.judgments.in_study(study_id)
        by_user = _labels_by_user(records)
        adjudicated = self.db.judgments.adjudications(study_id)
        items = Counter((r.query_external_id, r.doc_id) for r in records)
        pairs = [
            PairAgreement(a, b, len(by_user[a].keys() & by_user[b].keys()), kappa)
            for (a, b), kappa in pairwise_kappa(by_user).items()
        ]
        queries = []
        for query_id, external_id in sorted({(r.query_id, r.query_external_id) for r in records}):
            in_query = [r for r in records if r.query_id == query_id]
            query_labels = _labels_by_user(in_query)
            if len(query_labels) < 2:
                continue
            queries.append(
                QueryAgreement(
                    query_id=query_id,
                    external_id=external_id,
                    annotators=len(query_labels),
                    disagreements=len(disagreements(query_labels)),
                    adjudicated=len({r.member_id for r in in_query} & adjudicated.keys()),
                    alpha=alpha(query_labels, label_names),
                )
            )
        return AgreementReport(
            alpha=alpha(by_user, label_names),
            items_with_two_or_more=sum(count >= 2 for count in items.values()),
            label_counts={name: n for name in label_names if (n := sum(r.label == name for r in records))},
            pairs=pairs,
            queries=sorted(queries, key=lambda q: -q.disagreements),
        )

    def disagreement_items(self, study_id: int, query_id: int) -> list[DisagreementItem]:
        """Return the images of a query the annotators disagree on, in pool order.

        Raises:
            NotFound: The query has no pool in this study.
        """
        pool = self.db.studies.pool_of(query_id)
        if pool is None or pool.query.study_id != study_id:
            raise NotFound(f"query {query_id} has no pool in study {study_id}")
        records = [r for r in self.db.judgments.in_study(study_id) if r.query_id == query_id]
        adjudicated = self.db.judgments.adjudications(study_id)
        labels: dict[int, dict[str, str]] = {}
        for r in records:
            labels.setdefault(r.member_id, {})[r.username] = r.label
        return [
            DisagreementItem(m.id, m.image_id, m.image.external_id, labels[m.id], adjudicated.get(m.id))
            for m in pool.members
            if m.id in labels and len(set(labels[m.id].values())) > 1
        ]

    def adjudicate(self, study_id: int, admin: UserRow, member_id: int, label: str) -> None:
        """Set an image's final label, which overrides the annotators' majority in the consensus qrels.

        Raises:
            NotFound: The study doesn't exist, or the image has no judgments in it.
            Invalid: The study has no such label.
        """
        study = self.studies.get(study_id)
        label_row = next((row for row in study.labels if row.name == label), None)
        if label_row is None:
            raise Invalid(f"unknown label {label!r}; labels are {[row.name for row in study.labels]}")
        if not any(r.member_id == member_id for r in self.db.judgments.in_study(study_id)):
            raise NotFound(f"pool member {member_id} has no judgments in study {study_id}")
        self.db.judgments.set_adjudication(member_id, label_row.id, admin.id)

    def export(self, study_id: int, name: Export, username: str | None) -> str:
        """Return one of the study's exports as text.

        Qrels hold only pools every image of which is labelled; consensus qrels and training pairs use the
        adjudicated label first, else the majority; ties stay undecided.

        Args:
            username: Whose labels, for `qrels`; unused by the others.

        Raises:
            NotFound: The study doesn't exist.
            Invalid: `qrels` without a username.
        """
        settings = settings_of(self.studies.get(study_id))
        grade_of = {label.name: label.grade for label in settings.labels}
        all_pools = {
            p.query.external_id: [m.image.external_id for m in p.members]
            for p in self.db.studies.list_pools(study_id)
        }
        records = self.db.judgments.in_study(study_id)
        if name == "actions":
            return "".join(
                json.dumps(action) + "\n" for action in self.db.judgments.actions_in_study(study_id)
            )
        if name == "qrels":
            if username is None:
                raise Invalid("the per-annotator qrels need a username")
            labels = _labels_by_query([r for r in records if r.username == username])
            return "".join(line + "\n" for line in qrels_lines(all_pools, labels, grade_of))
        adjudicated = self.db.judgments.adjudications(study_id)
        votes: dict[tuple[str, str, int], list[str]] = {}
        for r in records:
            votes.setdefault((r.query_external_id, r.doc_id, r.member_id), []).append(r.label)
        decided = {
            (query, doc): label
            for (query, doc, member_id), labels in votes.items()
            if (label := consensus(labels, adjudicated.get(member_id))) is not None
        }
        consensus_labels: dict[str, dict[str, str]] = {}
        for (query, doc), label in decided.items():
            consensus_labels.setdefault(query, {})[doc] = label
        if name == "consensus_qrels":
            return "".join(line + "\n" for line in qrels_lines(all_pools, consensus_labels, grade_of))
        return "".join(
            json.dumps(pair) + "\n" for pair in training_pairs(all_pools, consensus_labels, grade_of)
        )

    def members(self, study_id: int) -> list[Member]:
        """Return the study's members with their roles and assigned queries, by username.

        Raises:
            NotFound: The study doesn't exist.
        """
        self.studies.get(study_id)
        counts = self.db.judgments.assignment_counts(study_id)
        return [Member(name, role, counts.get(name, 0)) for name, role in self.db.users.members(study_id)]

    def ensure_pilot_open(self, study_id: int) -> None:
        """Check that the pilot can still change: it can until an annotation query is assigned.

        Raises:
            Conflict: Annotation has started.
        """
        annotation = {query.id for query in self.db.studies.list_queries(study_id) if not query.is_pilot}
        if any(q in annotation for _, q in self.db.judgments.assignment_pairs(study_id)):
            raise Conflict("annotation has started, so the pilot stays as it is")

    def assign_pilot(self, study_id: int, annotators: list[str], per_query: int) -> dict[str, int]:
        """Spread the pilot queries over these annotators, `per_query` each (see `assign`)."""
        return self._assign(study_id, True, annotators, per_query)

    def assign(self, study_id: int, per_query: int, annotators: list[str] | None = None) -> dict[str, int]:
        """Assign the annotation queries, every query that isn't a pilot query; this starts annotation.

        Args:
            per_query: How many annotators judge each query.
            annotators: Who; every annotator of the study by default.

        Returns:
            How many of the study's queries each annotator has now, pilot queries included.

        Raises:
            Invalid: Someone isn't an annotator of the study, or `per_query` is out of range.
        """
        return self._assign(study_id, False, annotators, per_query)

    def _assign(
        self, study_id: int, pilot: bool, annotators: list[str] | None, per_query: int
    ) -> dict[str, int]:
        """Spread the pilot or the annotation queries round robin; the other kind's assignments stay."""
        members = [name for name, role in self.db.users.members(study_id) if role == Role.ANNOTATOR]
        chosen = members if annotators is None else annotators
        if outside := sorted(set(chosen) - set(members)):
            raise Invalid(f"not annotators of study {study_id}: {', '.join(outside)}")
        if not 1 <= per_query <= len(chosen):
            raise Invalid(f"{per_query} annotators per query, but {len(chosen)} annotators are chosen")
        ids = {name: self.users.get(name).id for name in chosen}
        targets = [
            pool.query_id for pool in self.db.studies.list_pools(study_id) if pool.query.is_pilot == pilot
        ]
        if pilot and not targets:
            raise Invalid("choose pilot queries first")
        if pilot:
            self.ensure_pilot_open(study_id)
        retargeted = set(targets)
        kept = [(u, q) for u, q in self.db.judgments.assignment_pairs(study_id) if q not in retargeted]
        turn = cycle(chosen)
        pairs = []
        for query_id in targets:
            picked: set[str] = set()
            while len(picked) < per_query:
                picked.add(next(turn))
            pairs += [(ids[name], query_id) for name in sorted(picked)]
        self.db.judgments.replace_assignments(study_id, kept + pairs)
        return self.db.judgments.assignment_counts(study_id)
