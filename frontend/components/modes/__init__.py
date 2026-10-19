"""The judge page's modes: how an annotator works through a query, when each is offered, and its tour."""

from collections.abc import Callable
from dataclasses import dataclass

from client import QueryView, Settings
from components.judging import Judging
from components.modes import grouped, review, suggest


@dataclass(frozen=True, slots=True)
class Mode:
    """One mode of the judge page.

    Attributes:
        render: Draws the query's images in this mode.
        offered: Whether the mode is offered for this query under the study's settings.
        tour: The tour (`tours/*.json`) that explains it.
        reflows: Whether "Images per row" redraws the page: Review shares the columns out over its panels.
    """

    render: Callable[[Judging, QueryView, dict[int, bytes]], None]
    offered: Callable[[Settings, QueryView], bool]
    tour: str
    reflows: bool = False


MODES: dict[str, Mode] = {
    "Judge": Mode(grouped.render, lambda settings, view: True, "judge"),
    "Suggest": Mode(
        suggest.render,
        lambda settings, view: (
            settings.suggest.enabled
            and not view.is_pilot
            and view.pool_size >= settings.suggest.min_pool_size
        ),
        "suggest",
    ),
    "Review": Mode(review.render, lambda settings, view: settings.review.enabled, "review", reflows=True),
}
"""The modes in the order of the mode switch; the first is the default."""


def offered(settings: Settings, view: QueryView) -> list[str]:
    """Return the names of the modes offered for this query, in switch order."""
    return [name for name, mode in MODES.items() if mode.offered(settings, view)]


def tour(name: str, view: QueryView) -> str:
    """Return the tour for a mode; a pilot query in Judge mode has its own."""
    return "pilot" if name == "Judge" and view.is_pilot else MODES[name].tour
