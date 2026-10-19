"""What the judge page shares: the study and labels for this run, labelling, and per-query session state."""

from dataclasses import dataclass

import streamlit as st

import styles
from client import CaraClient, Label, QueryView, Settings, Study
from state import client, current_study


@dataclass(frozen=True, slots=True)
class Judging:
    """What the parts of the judge page share, built once per run and passed in: module globals would be
    shared by every session."""

    api: CaraClient
    study: Study
    token: str
    offered: list[Label]
    label_names: list[str]
    icon_of: dict[str, str]

    @property
    def settings(self) -> Settings:
        """Return the open study's settings."""
        return self.study.settings


def judging() -> Judging:
    """Return the shared values for this run: the client, the open study, its offered labels, their icons."""
    study = current_study()
    offered = [label for label in study.settings.labels if label.offered]
    return Judging(
        api=client(),
        study=study,
        token=st.session_state.token,
        offered=offered,
        label_names=[label.name for label in offered],
        icon_of={label.name: styles.label_icon(label) for label in study.settings.labels},
    )


def group_key(query_id: int, member_ids: list[int]) -> str:
    """Return the session key of a group's label bar (and of its kept-labels notice)."""
    return f"group:{query_id}:{min(member_ids)}:{len(member_ids)}"


# Per-query state in st.session_state. Several modules read and write it, so its keys are spelled only here.


def groups(query_id: int) -> list[list[int]]:
    """Return the query's groups as this annotator sees them, splits included; [] until they are set up."""
    found: list[list[int]] = st.session_state.get(f"groups:{query_id}", [])
    return found


def has_groups(query_id: int) -> bool:
    """Return whether the query's groups are set up in this session."""
    return f"groups:{query_id}" in st.session_state


def set_groups(query_id: int, member_ids: list[list[int]]) -> None:
    """Store the query's groups, in the order the page shows them."""
    st.session_state[f"groups:{query_id}"] = member_ids


def forget_groups(query_id: int) -> list[list[int]]:
    """Drop the query's groups, so the next run sets them up again from the server; return them."""
    dropped: list[list[int]] = st.session_state.pop(f"groups:{query_id}", [])
    return dropped


def kept(key: str) -> tuple[str | None, list[int]]:
    """Return a group's last label and the images labelled on their own that kept a different one."""
    found: tuple[str | None, list[int]] = st.session_state.get(f"kept:{key}", (None, []))
    return found


def collapse_key(query_id: int) -> str:
    """Return the widget key of the query's "Collapse judged" toggle."""
    return f"collapse:{query_id}"


def collapsed(query_id: int) -> bool:
    """Return whether "Collapse judged" was on when the annotator last left the query.

    The toggle's own state is dropped while another query is shown, so it is kept here for the return.
    """
    return bool(st.session_state.get(f"collapsed:{query_id}", False))


def remember_collapsed(query_id: int) -> bool:
    """Keep the toggle's current state for the return to the query, and return it."""
    value = bool(st.session_state[collapse_key(query_id)])
    st.session_state[f"collapsed:{query_id}"] = value
    return value


def take_pool_completed() -> bool:
    """Return whether the last label completed the pool (`on_label`), once."""
    return bool(st.session_state.pop("pool_completed", False))


def state(query_id: int) -> dict[int, tuple[str | None, str | None]]:
    """Return the query's labels in this session: label and how it was given, per pool member."""
    labels: dict[int, tuple[str | None, str | None]] = st.session_state[f"labels:{query_id}"]
    return labels


def load(view: QueryView) -> None:
    """Store the query's labels as the server sent them, replacing this session's copy."""
    st.session_state[f"labels:{view.query_id}"] = {m.member_id: (m.label, m.source) for m in view.members}


def on_label(
    ctx: Judging, query_id: int, member_ids: list[int], label: str, source: str, position: int | None
) -> None:
    """Save a label for images and update this session's copy (a button callback).

    A group label never overwrites an image labelled on its own, as on the server; those images are kept for
    the group's notice (`kept`). When the label completes the pool, the next run redraws the whole page.

    Args:
        source: How the label was given: `group`, `item`, `review` or `suggestion`.
        position: The group's place on the page, for the action log; None outside a group.
    """
    labels = state(query_id)
    if source != "group" and all(labels[m][0] == label for m in member_ids):
        return
    if source == "group":
        key = group_key(query_id, member_ids)
        st.session_state[key] = label
        # Images labelled one by one keep their label; the group says so and offers to set them too.
        kept = [m for m in member_ids if labels[m][1] not in (None, "group") and labels[m][0] != label]
        st.session_state[f"kept:{key}"] = (label, kept)
    was_complete = all(value[0] for value in labels.values())
    ctx.api.judge(ctx.study.id, query_id, member_ids, label, source, position)
    for member_id in member_ids:
        # Same rule as the server: a group click only overwrites labels that came from a group click.
        if source == "group" and labels[member_id][1] not in (None, "group"):
            continue
        labels[member_id] = (label, source)
    if not was_complete and all(value[0] for value in labels.values()):
        st.session_state.pool_completed = True
