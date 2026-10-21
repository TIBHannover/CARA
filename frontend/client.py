"""The only module that talks to the CARA API.

The models mirror the API's response bodies (`cara.api.schemas`, `cara.settings` in the backend), whose
docstrings explain the fields. They ignore fields they don't know, so a newer server doesn't break an older
page.
"""

from collections.abc import Iterator

import httpx
from pydantic import BaseModel, ConfigDict, TypeAdapter


class Model(BaseModel):
    """A response body: frozen, and unknown fields are ignored."""

    model_config = ConfigDict(frozen=True, extra="ignore")


class Label(Model):
    """One answer an annotator can give (`cara.settings.Label`)."""

    name: str
    grade: int | None
    colour: str
    short: str | None = None
    icon: str | None = None
    offered: bool = True


class Display(Model):
    """How the judge page looks (`cara.settings.DisplaySettings`)."""

    thumb_px: int
    query_px: int
    cols: int
    drag_and_drop: bool = True
    split: bool = True
    group_order: str = "similarity"


class Review(Model):
    """The review round after a pool is labelled (`cara.settings.ReviewSettings`)."""

    enabled: bool
    required: bool
    negatives_shown: int


class Suggest(Model):
    """Suggest mode (`cara.settings.SuggestSettings`)."""

    enabled: bool = False
    min_seeds: int = 2
    min_pool_size: int = 0
    min_margin: float = 0.05
    merge_percentile: float = 50.0


class Pool(Model):
    """Which images each query is judged against (`cara.settings.PoolSettings`)."""

    source: str
    k: int | None
    max_size: int
    encoders: list[str] = []
    seed: int = 0


class Solo(Model):
    """Which images are judged one by one (`cara.settings.SoloSettings`)."""

    percentile: float


class Settings(Model):
    """A study's settings (`cara.settings.StudySettings`), sent back whole when an admin saves them."""

    # Keeps keys this client does not know, so saving never drops a newer server setting.
    model_config = ConfigDict(frozen=True, extra="allow")

    name: str
    encoder: str | None
    labels: list[Label]
    pool: Pool
    grouping: dict[str, str | int | float]
    solo: Solo
    top_k_individual: int
    order: str
    query_order: str = "shuffled"
    demo: bool = False
    review: Review
    annotators_per_query: int
    display: Display
    suggest: Suggest = Suggest()


class SuggestedCluster(Model):
    """Unjudged images that Suggest mode proposes one label for."""

    seeds: list[int]  # the marked images it follows: one, or several near-identical ones; none: no suggestion
    label: str | None
    members: list[int]


class Suggestions(Model):
    """Suggest mode for one query: whether it has enough marked images yet, and its suggestions."""

    ready: bool
    relevant_seeds: int
    nonrelevant_seeds: int
    min_seeds: int
    clusters: list[SuggestedCluster]


class Overview(Model):
    """Where a study stands; sent to its admins only."""

    stage: str
    pilot_queries: int
    pilot_judged: int
    annotation_queries: int
    annotation_assignments: int
    annotation_complete: int


class Study(Model):
    """A study as the logged-in user sees it, with their role in it."""

    id: int
    name: str
    role: str
    locked: bool
    settings: Settings
    dataset: str = ""
    query_set: str = ""
    query_kind: str | None = None
    cover_image_ids: list[int] = []
    overview: Overview | None = None


class QueueItem(Model):
    """One query in the annotator's queue, with how far they got."""

    query_id: int
    external_id: str
    pool_size: int
    judged: int
    reviewed: bool
    is_pilot: bool = False
    image_id: int | None = None
    text: str | None = None


class Member(Model):
    """One pool image as the annotator sees it, with their label and how they gave it."""

    member_id: int
    image_id: int
    doc_id: str
    score: float
    label: str | None
    source: str | None


class Group(Model):
    """A group of similar pool images."""

    group_id: int | None
    members: list[Member]


class QueryView(Model):
    """A query as the annotator sees it: its groups (with their own splits), the images judged alone."""

    query_id: int
    external_id: str
    image_id: int | None
    text: str | None
    groups: list[Group]
    individual: list[Member]
    judged: int
    pool_size: int
    reviewed: bool
    is_pilot: bool = False
    undoable_splits: int = 0

    @property
    def members(self) -> list[Member]:
        """Return every pool image: the groups' in group order, then the ones judged alone."""
        return [m for group in self.groups for m in group.members] + self.individual


class PilotAnnotatorStats(Model):
    """One annotator in the pilot report: speed, label shares, and agreement with the others."""

    username: str
    queries_judged: int
    images: int
    seconds_per_image: float | None
    active_minutes: float
    corrections: int
    relevant_share: float | None
    unsure_share: float | None
    kappa: float | None
    acc_relevant: float | None
    acc_nonrelevant: float | None
    compared: int


class PilotReport(Model):
    """The pilot's results: agreement over all pilot queries, and each annotator's numbers."""

    pilot_queries: int
    alpha: float | None
    annotators: list[PilotAnnotatorStats]


class PilotAnnotator(Model):
    """An annotator whose pilot judgments the simulator can use as ground truth."""

    username: str
    judged: int
    kappa: float | None


class SimulatorScope(Model):
    """What a simulation of the study can draw on: its queries, images and labelled pilot queries."""

    queries: int
    images: int
    pilot_queries: int
    labelled_pilot_queries: int
    pilot_annotators: list[PilotAnnotator] = []


class AnnotatorResult(Model):
    """One simulated annotator type under one setting; `_pc` values are per candidate image."""

    name: str
    seconds_pc: float | None
    recall: float | None
    min_seconds_pc: float | None = None
    best_tradeoff: bool


class SettingResult(Model):
    """One candidate setting's simulated effort and recall, per annotator type."""

    strategy: str
    grouping: dict[str, str | int | float]
    solo_percentile: float
    top_k_individual: int
    is_current: bool
    queries: int
    groups_per_pool: float
    individual_share: float
    min_actions_pc: float
    actions_pc: float | None
    recall_uncorrected: float | None
    annotators: list[AnnotatorResult]


class SimulatorEvent(Model):
    """One progress line of a simulation; the last carries the results, a failure has step "error"."""

    step: str
    title: str
    done: int
    total: int
    message: str
    results: list[SettingResult] | None = None
    images_in_study: int | None = None


class ProgressRow(Model):
    """One study member's progress."""

    username: str
    role: str
    queries: int
    complete: int
    reviewed: int
    judgments: int
    median_seconds_per_action: float | None
    active_minutes: float = 0.0


class PairAgreement(Model):
    """Cohen's kappa between two annotators, over the images both judged."""

    annotator_a: str
    annotator_b: str
    shared_items: int
    kappa: float | None


class QueryAgreement(Model):
    """Agreement on one query: Krippendorff's alpha, images disputed or Unsure, and final labels set."""

    query_id: int
    external_id: str
    is_pilot: bool
    image_id: int | None
    text: str | None
    annotators: int
    disagreements: int
    unsure: int
    adjudicated: int
    alpha: float | None


class AgreementReport(Model):
    """Agreement over the whole study, per annotator pair and per query."""

    alpha: float | None
    items_with_two_or_more: int
    label_counts: dict[str, int] = {}
    pairs: list[PairAgreement]
    queries: list[QueryAgreement]


class JudgedItem(Model):
    """A judged pool image, with each annotator's label and the final label, if any."""

    member_id: int
    image_id: int
    doc_id: str
    labels: dict[str, str]
    adjudicated: str | None


class PilotChoice(Model):
    """The pilot queries, and how many queries each annotator now has."""

    queries: list[str]
    assigned: dict[str, int]


class TeamMember(Model):
    """A study member, their role, and how many queries they are assigned."""

    username: str
    role: str
    assigned: int


class QuerySet(Model):
    """What a new study can do with one query set of a dataset."""

    name: str
    queries: int
    kind: str
    given_pools: bool
    knn_encoders: list[str]
    given_encoders: list[str]


class Dataset(Model):
    """A dataset at a glance, with its query sets."""

    id: int
    name: str
    description: str
    images: int
    query_sets: dict[str, int]
    encoders: dict[str, int]
    studies: int
    sets: list[QuerySet] = []


class Me(Model):
    """The logged-in account."""

    username: str
    is_superuser: bool


class AuthError(Exception):
    """The login token is missing, expired or revoked (HTTP 401); the page logs the person out."""


class ApiError(Exception):
    """Any other failed request; the message is `<status>: <the API's detail>`."""


def _error(response: httpx.Response) -> AuthError | ApiError:
    try:
        body = response.json()
    except ValueError:  # not JSON, e.g. a proxy's error page
        body = None
    detail = body.get("detail", response.text) if isinstance(body, dict) else response.text
    if isinstance(detail, list):  # a request that failed validation (422): one entry per field
        detail = "; ".join(f"{'.'.join(map(str, e['loc'][1:]))}: {e['msg']}" for e in detail)
    if response.status_code == 401:
        return AuthError(detail or "login expired")
    return ApiError(f"{response.status_code}: {detail or response.reason_phrase}")


def _as[T](kind: type[T], response: httpx.Response) -> T:
    """Parse a response body as `kind`: a model, or a type such as `list[Study]`."""
    return TypeAdapter(kind).validate_json(response.content)


class CaraClient:
    """A client for one user's requests.

    Every method raises `AuthError` when the token is no longer valid and `ApiError` for any other failure.
    """

    def __init__(self, base_url: str, token: str | None = None) -> None:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._http = httpx.Client(base_url=base_url, headers=headers, timeout=30)

    def _send(
        self,
        method: str,
        path: str,
        *,
        json: object = None,
        data: dict[str, str] | None = None,
        params: dict[str, int] | dict[str, str] | httpx.QueryParams | None = None,
    ) -> httpx.Response:
        response = self._http.request(method, path, json=json, data=data, params=params)
        if response.is_error:
            raise _error(response)
        return response

    def login(self, username: str, password: str) -> str:
        """Log in and return the token for `CaraClient(…, token)`; wrong credentials raise `AuthError`."""
        response = self._send("POST", "/auth/token", data={"username": username, "password": password})
        token: str = response.json()["access_token"]
        return token

    def studies(self) -> list[Study]:
        """Return the studies the user is a member of."""
        return _as(list[Study], self._send("GET", "/studies"))

    def study(self, study_id: int) -> Study:
        """Return one study."""
        return _as(Study, self._send("GET", f"/studies/{study_id}"))

    def set_pilot(
        self, study_id: int, count: int | None, annotators: list[str], per_query: int, seed: int = 0
    ) -> PilotChoice:
        """Draw `count` pilot queries (None: keep the current ones) and assign them to `annotators`.

        Raises:
            ApiError: 409 once a study query is assigned: the pilot can no longer change.
        """
        body = {"count": count, "annotators": annotators, "per_query": per_query, "seed": seed}
        return _as(PilotChoice, self._send("PUT", f"/studies/{study_id}/pilot", json=body))

    def pilot_report(self, study_id: int) -> PilotReport:
        """Return the pilot's results so far."""
        response = self._send("GET", f"/studies/{study_id}/pilot/report")
        return _as(PilotReport, response)

    def simulator_scope(self, study_id: int, pilot_users: list[str] | None = None) -> SimulatorScope:
        """Return what a simulation can draw on, counting only `pilot_users`' pilot labels if given."""
        params = httpx.QueryParams({"pilot_users": pilot_users} if pilot_users is not None else {})
        response = self._send("GET", f"/studies/{study_id}/simulator/scope", params=params)
        return _as(SimulatorScope, response)

    def sample_qrels(self, study_id: int) -> str | None:
        """Return the example qrels the study's dataset ships, or None if it ships none."""
        response = self._http.get(f"/studies/{study_id}/simulator/sample-qrels")
        if response.status_code == 404:
            return None
        if response.is_error:
            raise _error(response)
        return response.text

    def simulate(
        self,
        study_id: int,
        source: str,
        qrels: str | None,
        max_queries: int,
        plan: dict[str, object],
        pilot_users: list[str] | None = None,
    ) -> Iterator[SimulatorEvent]:
        """Run the settings simulator, yielding one event per step as it runs.

        The last event carries the results. A failure after the run has started arrives as an event with step
        "error", not as an exception.
        """
        body = {
            "source": source,
            "qrels": qrels,
            "max_queries": max_queries,
            "plan": plan,
            "pilot_users": pilot_users,
        }
        # A run takes from seconds to minutes; events keep the connection busy, so only a stall times out.
        timeout = httpx.Timeout(30, read=300)
        with self._http.stream(
            "POST", f"/studies/{study_id}/simulator/stream", json=body, timeout=timeout
        ) as response:
            if response.is_error:
                response.read()
                raise _error(response)
            for line in response.iter_lines():
                if line:
                    yield SimulatorEvent.model_validate_json(line)

    def me(self) -> Me:
        """Return the logged-in account."""
        return _as(Me, self._send("GET", "/auth/me"))

    def datasets(self) -> list[Dataset]:
        """Return every dataset, with what a new study can do with each query set (superusers)."""
        return _as(list[Dataset], self._send("GET", "/datasets"))

    def usernames(self) -> list[str]:
        """Return every account's username."""
        return _as(list[str], self._send("GET", "/users"))

    def create_study(self, body: dict[str, object]) -> Study:
        """Create a study on a dataset: sample its queries, build and group its pools.

        `body` is the API's `StudyIn`. Large pools take minutes, so the read timeout is ten minutes.
        """
        response = self._http.post("/studies", json=body, timeout=httpx.Timeout(30, read=600))
        if response.is_error:
            raise _error(response)
        return _as(Study, response)

    def delete_study(self, study_id: int) -> None:
        """Delete a study with every judgment in it (superusers); the dataset and the accounts stay."""
        self._send("DELETE", f"/studies/{study_id}")

    def progress(self, study_id: int) -> list[ProgressRow]:
        """Return each member's progress (admins)."""
        response = self._send("GET", f"/studies/{study_id}/admin/progress")
        return _as(list[ProgressRow], response)

    def agreement(self, study_id: int) -> AgreementReport:
        """Return the study's agreement report (adjudicators and admins)."""
        return _as(AgreementReport, self._send("GET", f"/studies/{study_id}/adjudication/agreement"))

    def judged_items(self, study_id: int, query_id: int) -> list[JudgedItem]:
        """Return the judged images of one query with every annotator's label (adjudicators and admins)."""
        response = self._send("GET", f"/studies/{study_id}/adjudication/items/{query_id}")
        return _as(list[JudgedItem], response)

    def adjudicate(self, study_id: int, member_id: int, label: str | None) -> None:
        """Set one pool image's final label, or take it back with None (adjudicators and admins)."""
        body = {"member_id": member_id, "label": label}
        self._send("PUT", f"/studies/{study_id}/adjudication/final-labels", json=body)

    def export(self, study_id: int, name: str, username: str | None = None) -> str:
        """Return the export `name` as text, for every annotator or only `username` (admins)."""
        params = {"username": username} if username else None
        return self._send("GET", f"/studies/{study_id}/admin/exports/{name}", params=params).text

    def members(self, study_id: int) -> list[TeamMember]:
        """Return the study's members."""
        return _as(list[TeamMember], self._send("GET", f"/studies/{study_id}/members"))

    def set_member(self, study_id: int, username: str, role: str) -> None:
        """Add a user to the study, or change their role (admins)."""
        self._send("PUT", f"/studies/{study_id}/members", json={"username": username, "role": role})

    def create_user(self, username: str, password: str) -> None:
        """Create an account (superusers); an existing username raises `ApiError` (409)."""
        self._send("POST", "/users", json={"username": username, "password": password})

    def assign(self, study_id: int, per_query: int, annotators: list[str] | None = None) -> dict[str, int]:
        """Assign the study queries (all but the pilot ones) to `annotators`, which starts annotation.

        Returns:
            How many queries each annotator now has.
        """
        body = {"per_query": per_query, "annotators": annotators}
        response = self._send("PUT", f"/studies/{study_id}/assignments", json=body)
        return _as(dict[str, int], response)

    def regroup(self, study_id: int) -> None:
        """Group every pool again with the current settings (before judging starts)."""
        self._send("POST", f"/studies/{study_id}/groups")

    def rebuild_pools(self, study_id: int) -> None:
        """Build every pool again with the current pool settings, then group them (before judging starts)."""
        self._send("POST", f"/studies/{study_id}/pools")

    def update_settings(self, study_id: int, settings: Settings) -> Study:
        """Save the study's settings and return the study.

        Raises:
            ApiError: 409 if judging has started and `settings` changes one that is locked by then.
        """
        response = self._send("PUT", f"/studies/{study_id}/settings", json=settings.model_dump(mode="json"))
        return _as(Study, response)

    def queue(self, study_id: int) -> list[QueueItem]:
        """Return the annotator's queries, in their order."""
        return _as(list[QueueItem], self._send("GET", f"/studies/{study_id}/queue"))

    def query(self, study_id: int, query_id: int) -> QueryView:
        """Return one query as the annotator sees it."""
        return _as(QueryView, self._send("GET", f"/studies/{study_id}/queries/{query_id}"))

    def judge(
        self,
        study_id: int,
        query_id: int,
        member_ids: list[int],
        label: str | None,
        source: str,
        position: int | None,
    ) -> None:
        """Label pool images in one action, or take their labels back (`label` None).

        `source` says how the label was given (a group click, a single image, review, a suggestion); a group
        click never overwrites a label given to a single image. `position` is the group's place on the page.
        """
        body = {"member_ids": member_ids, "label": label, "source": source, "group_position": position}
        self._send("POST", f"/studies/{study_id}/queries/{query_id}/judgments", json=body)

    def similar(self, study_id: int, query_id: int, to: list[int], k: int) -> list[int]:
        """Return the `k` pool images most like any of `to`, most similar first."""
        params = httpx.QueryParams({"to": to, "k": k})
        response = self._send("GET", f"/studies/{study_id}/queries/{query_id}/similar", params=params)
        return _as(list[int], response)

    def suggestions(self, study_id: int, query_id: int) -> Suggestions:
        """Return Suggest mode's suggestions for one query."""
        response = self._send("GET", f"/studies/{study_id}/queries/{query_id}/suggestions")
        return _as(Suggestions, response)

    def split(self, study_id: int, query_id: int, member_ids: list[int]) -> list[list[int]]:
        """Split a group in two, for this annotator only; return the two halves."""
        response = self._send(
            "POST", f"/studies/{study_id}/queries/{query_id}/split", json={"member_ids": member_ids}
        )
        return _as(list[list[int]], response)

    def undo_split(self, study_id: int, query_id: int) -> list[int]:
        """Merge back the annotator's last split; return the merged group's members."""
        response = self._send("POST", f"/studies/{study_id}/queries/{query_id}/split/undo")
        return _as(list[int], response)

    def finish_review(self, study_id: int, query_id: int) -> None:
        """Mark the query as reviewed."""
        self._send("POST", f"/studies/{study_id}/queries/{query_id}/review")

    def image(self, study_id: int, image_id: int, size: int, square: bool) -> bytes:
        """Return an image as JPEG, `size` pixels on its longer side (`square`: cropped to a square)."""
        params = {"size": size, "square": int(square)}
        return self._send("GET", f"/studies/{study_id}/images/{image_id}", params=params).content
