"""Simulation step 4: what will run, the query sample, and the run with a progress bar per step."""

import time
from dataclasses import dataclass

import streamlit as st
from streamlit.delta_generator import DeltaGenerator

import styles
from client import ApiError, CaraClient, SimulatorEvent, SimulatorScope
from components.feedback import count
from components.simulator.annotators import MAX_TYPES
from components.simulator.ground_truth import SOURCES, GroundTruth
from components.simulator.methods import MAX_SETTINGS, Candidates


@dataclass(frozen=True, slots=True)
class SimulationRun:
    """A finished run, kept in session state for the results.

    Attributes:
        event: The last event, which carries the results.
        source: The labels it ran against, in words.
        seconds: How long it took.
        when: When it finished, as HH:MM.
    """

    event: SimulatorEvent
    source: str
    seconds: float
    when: str


def summary_and_run(
    api: CaraClient,
    study_id: int,
    scope: SimulatorScope,
    ground: GroundTruth,
    candidates: Candidates,
    annotators: list[dict[str, object]],
    result_key: str,
) -> None:
    """Draw step 4, the run in one glance (labels, annotators, settings, queries), and run it."""
    with styles.section("run", "4 · Summary"):
        usable = min(ground.usable, scope.queries)
        names = ", ".join(str(a["name"]) for a in annotators) or "none chosen"
        labels = SOURCES[ground.source] + (
            f" of {', '.join(ground.pilot_users)}" if ground.pilot_users else ""
        )
        problems = [
            text
            for text, failed in [
                ("labels to simulate against", not ground.ready),
                ("an annotator type", not annotators),
                (f"at most {MAX_TYPES} annotator types", len(annotators) > MAX_TYPES),
                ("a value for every grouping option", not candidates.complete),
                (f"at most {MAX_SETTINGS} settings", candidates.total > MAX_SETTINGS),
            ]
            if failed
        ]
        st.markdown(
            f"- **Labels**: {labels} ({count(usable, 'query')} usable)\n"
            f"- **Annotators**: {names}\n"
            f"- **Settings**: {count(candidates.total, 'setting')}, including one image at a time"
        )
        queries = st.slider(
            "Queries to replay", 1, max(2, usable), min(30, max(1, usable)), disabled=usable <= 1
        )
        minutes = max(1, round(queries * (0.25 + candidates.total * 0.05) / 60))
        st.caption(f"A random sample; more queries give steadier numbers. About {minutes} min.")
        if problems:
            st.warning("Still needed: " + "; ".join(problems) + ".", icon=":material/rule:")
        if not st.button(
            "Run the simulation", type="primary", icon=":material/play_arrow:", disabled=bool(problems)
        ):
            return
        plan = candidates.plan | {"annotators": annotators}
        started = time.perf_counter()
        bars: dict[str, DeltaGenerator] = {}
        log: list[str] = []
        final: SimulatorEvent | None = None
        with st.status("Running the settings simulator", expanded=True) as status:
            progress_area = st.container()
            log_area = st.empty()
            try:
                for event in api.simulate(
                    study_id, ground.source, ground.qrels, queries, plan, ground.pilot_users
                ):
                    if event.step == "error":
                        status.update(label=f"Stopped: {event.message}", state="error")
                        log.append(f"error: {event.message}")
                    else:
                        if event.step not in bars:
                            bars[event.step] = progress_area.progress(0.0, text=event.title)
                        text = f"{event.title} · {event.done} of {event.total}"
                        bars[event.step].progress(event.done / max(event.total, 1), text=text)
                        log.append(f"{time.perf_counter() - started:5.1f} s  {event.message}")
                        if event.results is not None:
                            final = event
                    log_area.code("\n".join(log[-14:]), language=None)
            except ApiError as error:
                status.update(label=f"Stopped: {error}", state="error")
            if final is not None:
                st.session_state[result_key] = SimulationRun(
                    event=final,
                    source=labels,
                    seconds=time.perf_counter() - started,
                    when=time.strftime("%H:%M"),
                )
                status.update(label=f"Done in {time.perf_counter() - started:.0f} s", state="complete")
