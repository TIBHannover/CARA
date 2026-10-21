"""Simulation step 2: the simulated annotator types, one card each, with their accuracy and speed."""

import base64
from dataclasses import dataclass

import streamlit as st

import styles
from client import PilotAnnotatorStats

PRESETS: dict[str, dict[str, float]] = {
    # Typical: accuracy from Villa & Halvey (SIGIR 2013), about 5 s per single image from Halvey & Villa
    # (SIGIR 2014). Expert and novice are illustrative variations of it, not measurements. Perfect and
    # careless judge without errors or without corrections, at the typical annotator's speed.
    "Typical": {
        "acc_relevant": 0.68,
        "acc_nonrelevant": 0.82,
        "full_inspection_size": 8,
        "inspect_prob_large": 0.7,
        "single_s": 5.0,
        "group_action_s": 3.0,
        "override_s": 1.0,
        "split_s": 1.0,
        "browse_relevant_s": 1.4,
        "browse_nonrelevant_s": 0.2,
    },
    "Expert": {
        "acc_relevant": 0.85,
        "acc_nonrelevant": 0.95,
        "full_inspection_size": 16,
        "inspect_prob_large": 0.9,
        "single_s": 4.0,
        "group_action_s": 2.5,
        "override_s": 1.0,
        "split_s": 1.0,
        "browse_relevant_s": 1.2,
        "browse_nonrelevant_s": 0.2,
    },
    "Novice": {
        "acc_relevant": 0.6,
        "acc_nonrelevant": 0.75,
        "full_inspection_size": 6,
        "inspect_prob_large": 0.5,
        "single_s": 7.0,
        "group_action_s": 4.0,
        "override_s": 1.5,
        "split_s": 1.5,
        "browse_relevant_s": 1.8,
        "browse_nonrelevant_s": 0.3,
    },
}
PRESETS["Perfect"] = PRESETS["Careless"] = PRESETS["Typical"]
# The preset types, in the order they are shown, with the server's model for each.
TYPES = {
    "Perfect": "perfect",
    "Careless": "rubber_stamp",
    "Novice": "realistic",
    "Typical": "realistic",
    "Expert": "realistic",
}
# One colour per type, shared by its card and by the result charts.
COLOURS = {
    "Perfect": "#4F46E5",
    "Careless": "#E11D48",
    "Novice": "#F59E0B",
    "Typical": "#0EA5E9",
    "Expert": "#10B981",
}
PILOT_COLOURS = ["#8B5CF6", "#14B8A6", "#F97316", "#EC4899", "#84CC16"]
MAX_TYPES = 5  # the server's limit per run
ABOUT = {
    "Perfect": "Never errs: the fewest actions a setting allows.",
    "Careless": "Labels whole groups, never corrects an image.",
    "Novice": "Inspects few images, errs more often.",
    "Typical": "Accuracy and speed from user studies.",
    "Expert": "Inspects more, errs less.",
}
# Material Symbols "person" as an image: the HTML sanitiser drops inline SVG.
PERSON = (
    "data:image/svg+xml;base64,"
    + base64.b64encode(
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#FFFFFF"><path d="M12 12c2.21 '
        b"0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"
        b'"/></svg>'
    ).decode()
)


@dataclass(frozen=True, slots=True)
class Field:
    """One adjustable value of an annotator type, as the server's model or time model names it."""

    name: str
    label: str
    low: float
    high: float
    step: float
    slider: bool = False
    help: str | None = None

    def widget(self, value: float, key: str) -> None:
        """Draw the field's input with `value` as its default."""
        if self.slider:
            st.slider(self.label, self.low, self.high, value, self.step, key=key, help=self.help)
        elif self.step >= 1:
            st.number_input(self.label, int(self.low), int(self.high), int(value), key=key, help=self.help)
        else:
            st.number_input(self.label, self.low, self.high, value, self.step, key=key, help=self.help)


# How a realistic annotator judges (simulation.Realistic) and how long each action takes (TimeModel).
ACCURACY = [
    Field("acc_relevant", "Accuracy on Relevant images", 0.5, 1.0, 0.01, slider=True),
    Field("acc_nonrelevant", "Accuracy on Not Relevant images", 0.5, 1.0, 0.01, slider=True),
    Field(
        "full_inspection_size",
        "Groups looked at image by image up to (images)",
        1,
        64,
        1,
        help="In larger groups, each image is looked at only with the chance below.",
    ),
    Field(
        "inspect_prob_large", "Chance of looking at each image of a larger group", 0.0, 1.0, 0.05, slider=True
    ),
]
TIMES = [
    Field("single_s", "One image on its own", 0.5, 30.0, 0.5),
    Field("group_action_s", "Labelling a group", 0.5, 30.0, 0.5),
    Field("override_s", "Correcting an image", 0.1, 30.0, 0.1),
    Field("split_s", "Splitting a group", 0.1, 30.0, 0.1),
    Field("browse_relevant_s", "Looking at a Relevant image in a group", 0.0, 10.0, 0.1),
    Field("browse_nonrelevant_s", "Looking at a Not Relevant image in a group", 0.0, 10.0, 0.1),
]


@dataclass(frozen=True, slots=True)
class Kind:
    """An annotator type on a card: the server's model for it, its preset values, a line about it, its colour.

    What the admin changes in the card lives in session state, under `key`.

    Attributes:
        key: For widget keys and the card's CSS class, so without spaces.
    """

    name: str
    model: str
    values: dict[str, float]
    about: str
    colour: str
    key: str

    @property
    def realistic(self) -> bool:
        """Return whether the type decides at random, with the realistic model's accuracy and inspection."""
        return self.model == "realistic"

    def value(self, field: str) -> float:
        """Return what the admin set in the card, else the preset."""
        value: float = st.session_state.get(f"{field}-{self.key}", self.values[field])
        return value

    def card(self) -> bool:
        """Draw the type's card (who, key numbers, settings folded below); return whether to simulate it."""
        default = self.name == "Typical"
        chosen: bool = st.session_state.get(f"use-{self.key}", default)
        with st.container(border=True, key=f"annotator-{self.key}" + ("-on" if chosen else "")):
            with st.container(horizontal=True, vertical_alignment="center", gap="small"):
                st.html(
                    f'<div class="cara-avatar" style="background:{self.colour}">'
                    f'<img src="{PERSON}" alt=""></div>',
                    width="content",
                )
                st.markdown(f"**{self.name}**")
            st.caption(self.about)
            if self.realistic:
                st.markdown(
                    f"**{self.value('acc_relevant'):.0%}** · **{self.value('acc_nonrelevant'):.0%}** correct",
                    help="on Relevant · Not Relevant images",
                )
            else:
                st.markdown("No errors" if self.model == "perfect" else "No corrections")
            st.markdown(f"**{self.value('single_s'):g} s** per image on its own")
            use = st.toggle("Simulate", value=default, key=f"use-{self.key}")
            with st.expander("Adjust", icon=":material/tune:"):
                for field in ACCURACY if self.realistic else []:
                    field.widget(self.values[field.name], f"{field.name}-{self.key}")
                st.markdown("**Seconds per action**")
                for field in TIMES:
                    field.widget(self.values[field.name], f"{field.name}-{self.key}")
        return use

    def profile(self, repetitions: int) -> dict[str, object]:
        """Return the type as the server's `AnnotatorProfile` takes it."""
        model: dict[str, object] = {"kind": self.model}
        if self.realistic:
            model |= {field.name: self.value(field.name) for field in ACCURACY}
            model |= {
                "full_inspection_size": int(self.value("full_inspection_size")),
                "repetitions": repetitions,
            }
        return {"name": self.name, "model": model, "time": {f.name: self.value(f.name) for f in TIMES}}


def kinds(pilot: list[PilotAnnotatorStats]) -> list[Kind]:
    """Return the annotator types: the five presets, one per measured pilot annotator, and the admin's own."""
    found = [
        Kind(name, model, PRESETS[name], ABOUT[name], COLOURS[name], name.lower())
        for name, model in TYPES.items()
    ]
    for i, annotator in enumerate(pilot):
        measured = {}
        if annotator.acc_relevant is not None:
            measured["acc_relevant"] = round(max(0.5, annotator.acc_relevant), 2)
        if annotator.acc_nonrelevant is not None:
            measured["acc_nonrelevant"] = round(max(0.5, annotator.acc_nonrelevant), 2)
        if annotator.seconds_per_image is not None:
            measured["single_s"] = round(min(max(annotator.seconds_per_image, 0.5), 30.0), 1)
        if not measured:
            continue
        what = " and ".join(
            word for word, field in [("accuracy", "acc_relevant"), ("speed", "single_s")] if field in measured
        )
        found.append(
            Kind(
                f"{annotator.username[:30]} (pilot)",
                "realistic",
                PRESETS["Typical"] | measured,
                f"Typical, with the {what} measured in the pilot.",
                PILOT_COLOURS[i % len(PILOT_COLOURS)],
                f"pilot{i}",
            )
        )
    for i in range(st.session_state.get("custom-types", 0)):
        found.append(
            Kind(
                f"Custom {i + 1}",
                "realistic",
                PRESETS["Typical"],
                "Typical, to adjust.",
                "#64748B",
                f"custom{i}",
            )
        )
    return found


def _add_card() -> None:
    with st.container(
        border=True, key="annotator-add", vertical_alignment="center", horizontal_alignment="center"
    ):
        st.caption("Your own type, starting from Typical.")
        if st.button("Add a type", icon=":material/person_add:"):
            st.session_state["custom-types"] = st.session_state.get("custom-types", 0) + 1
            st.rerun()


def simulated_annotators(pilot: list[PilotAnnotatorStats]) -> list[dict[str, object]]:
    """Draw step 2, the annotator cards; return the profiles of the types switched on."""
    with styles.section("annotators", "2 · Simulated annotators"):
        st.caption(
            "Typical: accuracy from Villa & Halvey (SIGIR 2013), 5 s per image from Halvey & Villa (SIGIR "
            "2014). Novice and Expert are variations of it. Pilot annotators bring their measured accuracy "
            "and speed; adjust any type to match your annotators."
        )
        styles.annotator_cards()
        every = kinds(pilot)
        presets, more = every[: len(TYPES)], every[len(TYPES) :]
        with st.container(horizontal=True, key="annotator-cards-presets", gap="small"):
            chosen = [kind for kind in presets if kind.card()]
        with st.container(horizontal=True, key="annotator-cards-more", gap="small"):
            chosen += [kind for kind in more if kind.card()]
            _add_card()
        repetitions = st.number_input(
            "Repetitions per query",
            1,
            10,
            3,
            help="Realistic types decide at random; their results are averaged over these runs.",
        )
        if not chosen:
            st.warning("Switch on at least one annotator type.", icon=":material/person_off:")
        elif len(chosen) > MAX_TYPES:
            st.warning(f"Simulate at most {MAX_TYPES} types at once.", icon=":material/group_off:")
        return [kind.profile(int(repetitions)) for kind in chosen]
