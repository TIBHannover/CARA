"""Guided tours with driver.js (MIT; static/driverjs, served by the app itself): one per page or mode. A
person's first visit offers the tour and starts it only if they agree; the Tour button (top right) starts it
any time.

A step points at an element by CSS selector, usually a `st-key-<key>` class (see styles.py); steps whose
element is not on the page (no groups in a pilot query, say) are left out. Whether a tour was seen is kept
in the browser (localStorage), so it does not follow a person to another browser.
"""

import json

import streamlit as st

STATIC = "app/static/driverjs"
# The popover in the app's font and colours.
CSS = (
    ".driver-popover{font-family:inherit;border-radius:0.5rem;max-width:22rem;}"
    ".driver-popover-title{font-size:1.05rem;}"
    ".driver-popover-description{font-size:0.95rem;line-height:1.45;}"
    ".driver-popover-footer button{text-shadow:none;border-radius:0.375rem;padding:0.3rem 0.7rem;}"
    ".driver-popover-next-btn{background:#4F46E5 !important;color:#FFFFFF !important;"
    "border-color:#4F46E5 !important;}"
)
SCRIPT = """
(() => {
  const name = %(name)s, force = %(force)s, steps = %(steps)s, base = %(base)s;
  const seen = "cara-tour-" + name;
  try {
    // Never on its own in automated browsers (end-to-end tests), nor twice.
    if (!force && (navigator.webdriver || localStorage.getItem(seen))) return;
  } catch (error) {
    if (!force) return;
  }
  if (!document.getElementById("cara-driver-css")) {
    const link = Object.assign(document.createElement("link"), {
      id: "cara-driver-css", rel: "stylesheet", href: base + "/driver.css",
    });
    document.head.appendChild(link);
  }
  if (!document.getElementById("cara-driver-js")) {
    const script = Object.assign(document.createElement("script"), {
      id: "cara-driver-js", src: base + "/driver.js.iife.js",
    });
    document.head.appendChild(script);
  }
  // Streamlit draws the page in pieces: wait for the library and the first element, at most 15 s.
  const first = steps.find((step) => step.element);
  const started = Date.now();
  const start = () => {
    const ready = window.driver && window.driver.js && (!first || document.querySelector(first.element));
    if (!ready) {
      if (Date.now() - started < 15000) setTimeout(start, 200);
      return;
    }
    const shown = steps.filter((step) => !step.element || document.querySelector(step.element));
    const tour = () => window.driver.js.driver({
      showProgress: true,
      progressText: "{{current}} of {{total}}",
      steps: shown.map((step) => ({
        element: step.element || undefined,
        popover: { title: step.title, description: step.text },
      })),
    }).drive();
    if (force) return tour();
    // A first visit only asks; the tour starts if the person agrees. Either answer is remembered.
    const offer = window.driver.js.driver({
      steps: [{
        popover: {
          title: "New to this page?",
          description: "A short tour shows what everything here does. "
            + "You can also start it later with Tour, top right.",
          showButtons: ["next", "previous"],
          disableButtons: [],
          nextBtnText: "Show me",
          prevBtnText: "No thanks",
          onNextClick: () => { offer.destroy(); tour(); },
          onPrevClick: () => offer.destroy(),
        },
      }],
      onDestroyed: () => {
        try { localStorage.setItem(seen, "1"); } catch (error) {}
      },
    });
    offer.drive();
  };
  setTimeout(start, 300);
})();
"""


def tour(name: str, steps: list[tuple[str | None, str, str]]) -> None:
    """Offer tour `name` on a first visit and start it after `replay(name)`.

    Args:
        name: The tour's name, also the browser key that records it was seen.
        steps: (CSS selector, or None for a step without an element; title; text). Steps whose element is not
            on the page are left out.
    """
    runs = st.session_state.get(f"tour:{name}", 0)
    body = SCRIPT % {
        "name": json.dumps(name),
        "force": "true" if runs else "false",
        "steps": json.dumps([{"element": e, "title": t, "text": x} for e, t, x in steps]).replace(
            "</", "<\\/"
        ),
        "base": json.dumps(STATIC),
    }
    # The run count makes a replay a new element, so Streamlit draws it again and the script runs again.
    st.html(f"<style>{CSS}</style><script>/* {runs} */{body}</script>", unsafe_allow_javascript=True)


def replay(name: str) -> None:
    """Start tour `name` on the next run, even if it was seen (the Tour button's callback)."""
    st.session_state[f"tour:{name}"] = st.session_state.get(f"tour:{name}", 0) + 1


def button(name: str) -> None:
    """Draw the Tour button, pinned to the top right corner beside the app menu (`styles.base`)."""
    st.button(
        "Tour",
        icon=":material/tour:",
        key="tour-button",
        help="A short guided tour of this page",
        on_click=replay,
        args=(name,),
    )
