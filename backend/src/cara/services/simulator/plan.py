"""What the admin asks the simulator to compare: grouping methods with their values, and annotator types."""

from itertools import product
from typing import Literal, Self

from pydantic import Field, model_validator

from cara.grouping import GroupingSettings
from cara.grouping.agglomerative import Agglomerative
from cara.grouping.hdbscan import HDBSCAN
from cara.grouping.kmeans import KMeans
from cara.grouping.none import NoGrouping
from cara.settings import Frozen, StudySettings
from cara.simulation import Assessor, Realistic, Setting, TimeModel

Source = Literal["qrels", "pilot", "none"]
"""Where a run's ground truth comes from: an uploaded qrels file, the judged pilot queries, or none."""

MAX_CANDIDATES = 60
MAX_ANNOTATORS = 5


class AgglomerativeOptions(Frozen):
    """The agglomerative clustering values to try; every combination is one setting."""

    linkage: list[Literal["average", "complete", "single"]] = Field(default=["average"], min_length=1)
    max_size: list[int] = Field(default=[8, 16, 32], min_length=1)


class KMeansOptions(Frozen):
    """The k-means values to try; every combination is one setting."""

    n_groups: list[int] = Field(default=[10, 20], min_length=1)
    max_size: list[int] = Field(default=[16], min_length=1)


class HDBSCANOptions(Frozen):
    """The HDBSCAN values to try; every combination is one setting."""

    min_cluster_size: list[int] = Field(default=[3, 5], min_length=1)
    max_size: list[int] = Field(default=[16], min_length=1)


class AnnotatorProfile(Frozen):
    """A simulated annotator: how it judges (perfect, careless, realistic) and how long each action takes."""

    name: str = Field(default="Typical annotator", min_length=1, max_length=40)
    model: Assessor = Realistic(kind="realistic", repetitions=3)
    time: TimeModel = TimeModel()

    @property
    def repetitions(self) -> int:
        """How often each pool is replayed for this type: more than once only if it decides at random."""
        return self.model.runs()


class SimulatorPlan(Frozen):
    """What to simulate: every combination of the chosen values, judged by each annotator type.

    Judging one image at a time is always included as the reference, and so is the study's current setting.
    """

    agglomerative: AgglomerativeOptions | None = AgglomerativeOptions()
    kmeans: KMeansOptions | None = None
    hdbscan: HDBSCANOptions | None = None
    solo_percentile: list[float] = Field(default=[10.0], min_length=1)
    top_k_individual: list[int] = Field(default=[0], min_length=1)
    annotators: list[AnnotatorProfile] = Field(
        default=[AnnotatorProfile()], min_length=1, max_length=MAX_ANNOTATORS
    )

    @model_validator(mode="after")
    def _unique_annotator_names(self) -> Self:
        names = [annotator.name for annotator in self.annotators]
        if len(set(names)) != len(names):
            raise ValueError(f"annotator profiles need distinct names: {names}")
        return self

    def groupings(self) -> list[Agglomerative | KMeans | HDBSCAN]:
        """Return every grouping to compare: each combination of each chosen method's values."""
        found: list[Agglomerative | KMeans | HDBSCAN] = []
        if self.agglomerative:
            found += [
                Agglomerative(method="agglomerative", linkage=linkage, max_size=size)
                for linkage, size in product(self.agglomerative.linkage, self.agglomerative.max_size)
            ]
        if self.kmeans:
            found += [
                KMeans(method="kmeans", n_groups=k, max_size=size)
                for k, size in product(self.kmeans.n_groups, self.kmeans.max_size)
            ]
        if self.hdbscan:
            found += [
                HDBSCAN(method="hdbscan", min_cluster_size=m, max_size=size)
                for m, size in product(self.hdbscan.min_cluster_size, self.hdbscan.max_size)
            ]
        return found

    def candidates(self, current: StudySettings) -> list[Setting]:
        """Return the settings to compare, one image at a time first.

        Then every grouping with every rule for images judged alone, and the study's current setting if it
        isn't among them.
        """
        candidates = [
            Setting(name=describe(NoGrouping(method="none"), 0, 0), grouping=NoGrouping(method="none"))
        ]
        candidates += [
            Setting(
                name=describe(grouping, solo, top_k),
                grouping=grouping,
                solo_percentile=solo,
                top_k_individual=top_k,
            )
            for grouping, solo, top_k in product(
                self.groupings(), self.solo_percentile, self.top_k_individual
            )
        ]
        return _with_current(candidates, current)


def describe(grouping: GroupingSettings, solo: float, top_k: int) -> str:
    """Return a short, readable name for a candidate setting.

    The method's label, then its rules for images judged alone; one image at a time has none.
    """
    if not grouping.groups:
        return grouping.label()
    extras = [f"{solo:g}% isolated alone" if solo else "", f"top {top_k} alone" if top_k else ""]
    return ", ".join([grouping.label(), *[extra for extra in extras if extra]])


def _with_current(candidates: list[Setting], current: StudySettings) -> list[Setting]:
    key = (current.grouping, current.solo.percentile, current.top_k_individual)
    if all((c.grouping, c.solo_percentile, c.top_k_individual) != key for c in candidates):
        candidates.insert(
            0,
            Setting(
                name="current: "
                + describe(current.grouping, current.solo.percentile, current.top_k_individual),
                grouping=current.grouping,
                solo_percentile=current.solo.percentile,
                top_k_individual=current.top_k_individual,
            ),
        )
    return candidates


def default_plan(current: StudySettings) -> SimulatorPlan:
    """Common settings, compared when the admin chooses none: the study's isolated-image rule throughout."""
    return SimulatorPlan(
        agglomerative=AgglomerativeOptions(max_size=[8, 16, 24, 32]),
        kmeans=KMeansOptions(n_groups=[10], max_size=[16]),
        hdbscan=HDBSCANOptions(min_cluster_size=[3], max_size=[16]),
        solo_percentile=[current.solo.percentile],
        top_k_individual=[0, 10],
    )
