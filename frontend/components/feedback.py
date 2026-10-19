"""Short feedback for the judge page: counted nouns, and toasts that survive a rerun."""

import streamlit as st


def count(n: int, noun: str) -> str:
    """Return `n` with the noun, plural when it isn't 1 ("1 query", "2 queries")."""
    if n == 1:
        return f"1 {noun}"
    return (
        f"{n} {noun[:-1]}ies"
        if noun.endswith("y") and noun[-2:] not in ("ay", "ey", "oy")
        else f"{n} {noun}s"
    )


def percent(share: float | None) -> float | None:
    """Return a share (0 to 1) as a percentage for a table column; None stays None."""
    return None if share is None else 100 * share


def notify(text: str, icon: str) -> None:
    """Queue a short notification (st.toast) for an action, since a toast does not survive a rerun."""
    st.session_state.setdefault("toasts", []).append((text, icon))


def show_toasts() -> None:
    """Show the queued toasts (`notify`).

    Called at the top of the page and of each group fragment, since an action inside a fragment reruns only
    that fragment.
    """
    # Streamlit drops a toast that lands in the same slot as one still on screen, so consecutive toasts are
    # shifted to different slots by a few empty style tags (style-only HTML goes to the same, invisible area).
    for text, icon in st.session_state.pop("toasts", []):
        st.session_state.toast_count = st.session_state.get("toast_count", 0) + 1
        for _ in range(st.session_state.toast_count % 4):
            st.html("<style></style>")
        st.toast(text, icon=icon, duration="long")
