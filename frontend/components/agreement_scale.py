"""How to read agreement values: Landis & Koch (1977) for Cohen's kappa, Krippendorff (2004) for alpha."""

import streamlit as st

KAPPA = [
    (0.81, "almost perfect"),
    (0.61, "substantial"),
    (0.41, "moderate"),
    (0.21, "fair"),
    (0.0, "slight"),
    (-1.0, "poor"),
]
ALPHA = [(0.8, "reliable"), (0.667, "tentative"), (-1.0, "unreliable")]


def meaning(value: float | None, scale: list[tuple[float, str]]) -> str:
    """Return the word for an agreement value on `scale` (`KAPPA` or `ALPHA`); a dash for no value."""
    if value is None:
        return "–"
    return next(label for low, label in scale if value >= low)


def legend() -> None:
    """Draw a folded table of what κ and α values mean, with their sources."""
    with st.expander("How to read κ and α", icon=":material/menu_book:"):
        kappa, alpha = st.columns(2)
        with kappa:
            st.markdown("**Cohen's κ**, per pair (Landis & Koch, 1977)")
            st.dataframe(
                [
                    {"κ": "0.81 – 1.00", "agreement": "almost perfect"},
                    {"κ": "0.61 – 0.80", "agreement": "substantial"},
                    {"κ": "0.41 – 0.60", "agreement": "moderate"},
                    {"κ": "0.21 – 0.40", "agreement": "fair"},
                    {"κ": "0.00 – 0.20", "agreement": "slight"},
                    {"κ": "below 0", "agreement": "poor (worse than chance)"},
                ],
                hide_index=True,
            )
        with alpha:
            st.markdown("**Krippendorff's α**, all annotators (Krippendorff, 2004)")
            st.dataframe(
                [
                    {"α": "≥ 0.800", "labels are": "reliable"},
                    {"α": "0.667 – 0.800", "labels are": "good for tentative conclusions only"},
                    {"α": "below 0.667", "labels are": "unreliable"},
                ],
                hide_index=True,
            )
