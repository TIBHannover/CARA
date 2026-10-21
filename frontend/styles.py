"""How CARA looks: the CSS, label icons and colours, and the layout helpers for image grids and cards.

CSS rules target Streamlit's `st-key-<key>` classes, so the widget keys in app_pages/ and components/
are part of the look. :has() is only used on a few page-level elements: on every image of a ~200-image page
it made each full redraw seconds slower.
"""

from typing import Literal

import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from client import Label

# The theme's background is white, because Streamlit draws tables and segmented controls in it; the page
# itself is grey, so the white cards stand apart.
PAGE = "#F5F6F8"
CARDS = (
    '[class*="st-key-card-"]',
    ".st-key-query-panel",
    '[class*="st-key-box-open-"]',
    '[class*="st-key-panel-"]',
    '[class*="st-key-tile-"]',
    '[class*="st-key-annotator-"]:not([class*="st-key-annotator-cards"])',
    '[data-testid="stMetric"]',
    '[data-testid="stExpander"] details',
)
ICON = '[data-testid="stIconMaterial"]'

# A study's stage as the Studies cards and the study header show it: label, badge colour, icon.
STAGES: dict[str, tuple[str, Literal["gray", "orange", "blue", "green"], str]] = {
    "new": ("Not started", "gray", ":material/radio_button_unchecked:"),
    "pilot": ("Pilot", "orange", ":material/science:"),
    "annotation": ("Annotation", "blue", ":material/photo_library:"),
    "done": ("Done", "green", ":material/task_alt:"),
}


def card(name: str) -> DeltaGenerator:
    """Return a bordered white card; `name` must be unique on the page."""
    return st.container(border=True, key=f"card-{name}")


def section(name: str, title: str, expanded: bool = True) -> DeltaGenerator:
    """Return a white card that folds, for pages with several sections; `name` must be unique on the page."""
    return st.expander(f"**{title}**", expanded=expanded, key=f"section-{name}")


def heading(title: str, study_name: str) -> None:
    """Draw a page title with the study it acts on above it, so an admin never changes the wrong study."""
    st.caption(f":material/folder_open: Study · **{study_name}**")
    st.title(title)


def base() -> None:
    """Add the CSS every page shares: the page and card colours, font, top bar and Tour button."""
    st.html(
        "<style>"
        '[data-testid="stMainBlockContainer"]{padding-top:4.5rem;}'
        # Text grows with the window like the images: 14 px up to about 1300 px wide, 20 px on wide screens.
        "html{font-size:clamp(14px, calc(0.3125vw + 10px), 20px) !important;}"
        f'[data-testid="stAppViewContainer"],[data-testid="stHeader"]{{background:{PAGE};}}'
        + ",".join(CARDS)
        + "{background:#FFFFFF;}"
        # A section's title reads as a heading; expanders inside it keep their small labels.
        '[class*="st-key-section-"] > [data-testid="stExpander"] > details > summary p{font-size:1.2rem;}'
        # Study cards open with a strip of square tiles from the study.
        '[class*="st-key-cover-"]{display:grid !important;gap:0.4rem;'
        "grid-template-columns:repeat(4,minmax(0,1fr));}"
        '[class*="st-key-cover-"] img{aspect-ratio:1;object-fit:cover;border-radius:0.375rem;}'
        # The Tour button sits in the top bar, left of the app menu, on every page that has a tour.
        ".st-key-tour-button{position:fixed;top:0.55rem;right:3.6rem;z-index:999991;width:auto !important;}"
        # The studies page: as many card columns as fit the window; "New study" is a whole dashed card.
        '[class*="st-key-studies-grid"]{display:grid !important;gap:1rem;'
        "grid-template-columns:repeat(auto-fill,minmax(20rem,1fr));}"
        # Every card in a row as tall as the tallest, with its button at the bottom.
        '[class*="st-key-studies-grid"] > [data-testid="stLayoutWrapper"]{height:100%;}'
        '[class*="st-key-studies-grid"] [class*="st-key-card-"]{height:100%;}'
        '[class*="st-key-studies-grid"] [class*="st-key-card-"] > :last-child{margin-top:auto;}'
        # The New study card has a dashed space with a plus where the other cards show their images.
        ".st-key-new-cover{aspect-ratio:4/1;border:2px dashed #C7C9D1;border-radius:0.375rem;"
        "justify-content:center !important;align-items:center !important;}"
        ".st-key-new-cover p{text-align:center;margin:0;}"
        '.st-key-new-cover span[role="img"]{font-size:2.5rem;color:#A1A1AA;}</style>'
    )


def judge_page() -> None:
    """Add the judge page's CSS: the query panel, the group boxes and the image grids."""
    st.html(
        "<style>"
        # The mode switch stays on one line in a narrow panel: its buttons share the width and shrink.
        '[class*="st-key-mode-"] [role="radiogroup"]{flex-wrap:nowrap !important;}'
        '[class*="st-key-mode-"] [role="radiogroup"] button{flex:1 1 0;min-width:0;padding-left:0.3rem;'
        "padding-right:0.3rem;}"
        # The query panel keeps a usable width on small screens (the picker text and the mode switch fit);
        # the image column gives way. One :has() on the two columns, not on every image.
        '[data-testid="stHorizontalBlock"]:has(.st-key-query-panel){flex-wrap:nowrap !important;}'
        '[data-testid="stColumn"]:has(.st-key-query-panel){flex:0 0 max(17rem,20%) !important;min-width:0;}'
        # Keep the query in view while the candidate groups scroll past it (its column is page-high).
        # Streamlit wraps the panel in a layout element of its own height, so the wrapper is what sticks. The
        # panel never grows taller than the window: it stays in view whole while the images scroll.
        '[data-testid="stLayoutWrapper"]:has(> .st-key-query-panel){position:sticky;top:4.5rem;}'
        ".st-key-query-panel{max-height:calc(100vh - 5.5rem);overflow-y:auto;}"
        # Keep each image's full-screen button inside the image, where it cannot cover the Split button above.
        '[data-testid="stFullScreenFrame"] [data-testid="stElementToolbar"]{top:0.25rem !important;}'
        # Each group is a card: tinted header band, light shadow, space between cards.
        '[class*="st-key-box-open-"]{box-shadow:0 1px 3px rgba(24,24,27,0.10);margin-top:0.5rem;}'
        '[class*="st-key-head-open-"]{background:#F4F4F5;border-bottom:1px solid #E4E4E7;'
        # A bordered container has 13 px padding and a 1 px border: the band reaches over both to the edges.
        "margin:-14px -14px 0.25rem -14px;width:calc(100% + 28px);max-width:none !important;"
        "padding:0.5rem 13px;"
        "border-radius:0.5rem 0.5rem 0 0;}"
        # The header wraps when narrow: label bar and Split move to a second line instead of being cut off.
        '[class*="st-key-head-open-"],[class*="st-key-sughead-"]{flex-wrap:wrap !important;row-gap:0.5rem;}'
        # A group taller than most of the screen scrolls inside its box, so the next group's header stays in
        # sight below it; the navigator above the groups jumps to any group (anchors sit below the top bar).
        '[class*="st-key-grid-item-"],[class*="st-key-grid-sug-"]'
        # Padding inside the scroll box keeps the label frame round each image (3 px, outside it) visible.
        "{max-height:68vh;overflow-y:auto;padding:4px 0.35rem 4px 4px;}"
        ".cara-anchor{scroll-margin-top:5.5rem;}"
        # Adjudication: each annotator's label under an image, in the label's colour.
        ".cara-votes{display:flex;flex-wrap:wrap;gap:0 0.6rem;font-size:0.8rem;line-height:1.3;}"
        ".cara-groups{display:flex;flex-wrap:wrap;gap:0.4rem;}"
        ".cara-groups a{padding:0.15rem 0.6rem;border:1px solid #E4E4E7;border-radius:1rem;"
        "background:#FFFFFF;color:inherit;text-decoration:none;font-size:0.85rem;}"
        ".cara-groups a:hover{border-color:#4F46E5;color:#4F46E5;}"
        ".cara-groups a span{color:#71717A;}"
        ".cara-groups .cara-order{align-self:center;margin-right:0.25rem;font-size:0.85rem;color:#71717A;}"
        # Judge mode's image grids: "Images per row" is one variable (set by the slider), so changing it
        # rebuilds no element.
        '[class*="st-key-grid-"]{display:grid !important;gap:1rem 0.75rem;'
        "grid-template-columns:repeat(var(--cara-cols),minmax(0,1fr));}"
        # Buttons under each image: the label buttons share the row. Icons and buttons scale with the tile's
        # width (container query units), so many images per row still fit one row of usable buttons.
        '[class*="st-key-cell-"],[class*="st-key-tile-"]{container-type:inline-size;}'
        '[class*="st-key-item-"] button,[class*="st-key-review-"] button'
        "{min-height:clamp(1.8rem,15cqi,2.4rem);padding:0.15rem clamp(0.1rem,2cqi,0.4rem);}"
        '[class*="st-key-item-"] button span[role="img"],'
        '[class*="st-key-review-"] button span[role="img"]{font-size:clamp(0.95rem,10cqi,1.4rem);}'
        # On narrow tiles (many images per row) the row stays on one line and its buttons shrink instead.
        '[class*="st-key-item-"][class*="-labels"],[class*="st-key-review-"][class*="-labels"]'
        "{flex-wrap:nowrap !important;}"
        '[class*="st-key-item-"][class*="-labels"] > div,[class*="st-key-review-"][class*="-labels"] > div,'
        '[class*="st-key-item-"] button,[class*="st-key-review-"] button{min-width:0 !important;}</style>'
    )


def new_study() -> None:
    """Make the two sections of each New study row equally tall, so the page reads as a grid of cards."""
    st.html(
        "<style>"
        '[class*="st-key-new-row-"] [data-testid="stHorizontalBlock"]{align-items:stretch !important;}'
        # Only the section itself fills its column, and only while open: a folded one shrinks to its title.
        '[class*="st-key-new-row-"] [data-testid="stColumn"] > [data-testid="stVerticalBlock"],'
        '[class*="st-key-new-row-"] [data-testid="stColumn"] > * > [data-testid="stLayoutWrapper"],'
        '[class*="st-key-new-row-"] [data-testid="stColumn"] > * > * > [data-testid="stExpander"],'
        '[class*="st-key-new-row-"] [data-testid="stColumn"] > * > * > * > details[open]{height:100%;}'
        "</style>"
    )


def profile_bar() -> None:
    """Style the simulator's profile switch as a tinted band, so it reads as a switch for all its results."""
    st.html(
        "<style>.st-key-profile-bar{background:rgba(79,70,229,0.07);border:1px solid rgba(79,70,229,0.35);"
        "border-left:4px solid #4F46E5;border-radius:0.5rem;padding:0.5rem 0.75rem;gap:1rem;}"
        '.st-key-profile-bar button[data-selected="true"]'
        "{background:#4F46E5 !important;color:#FFFFFF !important;border-color:#4F46E5 !important;}</style>"
    )


def annotator_cards() -> None:
    """Lay the simulator's annotator cards out in rows of five (fewer on narrow screens); fade unused ones."""
    st.html(
        "<style>"
        '[class*="st-key-annotator-cards"]{display:grid !important;'
        "grid-template-columns:repeat(5,minmax(0,1fr));}"
        '@media (max-width:1100px){[class*="st-key-annotator-cards"]'
        "{grid-template-columns:repeat(auto-fill,minmax(12rem,1fr));}}"
        '[class*="st-key-annotator-"]:not([class*="-on"]):not([class*="st-key-annotator-cards"]) .cara-avatar'
        "{opacity:0.35;}"
        ".cara-avatar{width:2.2rem;height:2.2rem;border-radius:50%;display:flex;align-items:center;"
        "justify-content:center;}.cara-avatar img{width:1.4rem;height:1.4rem;}</style>"
    )


def images_per_row(cols: int) -> None:
    """Set how many images an image grid shows per row (one CSS variable, so the tiles aren't redrawn)."""
    st.html(f"<style>:root{{--cara-cols:{cols};}}</style>")


def tint_judged(on: bool) -> None:
    """Show or hide the tint in its label's colour over each judged image (one CSS variable)."""
    st.html(f"<style>:root{{--cara-tint:{0.3 if on else 0};}}</style>")


def review_board(panels: list[str], hints_prefix: str, widths: list[int], colours: list[str]) -> None:
    """Style the review board: one card per label column, in the label's colour, each scrolling on its own.

    Each panel is its own grid of `widths[i]` columns (its share of "Images per row"). A header band and a
    border in the label's colour, over a faint tint of it, make the column an image sits in, and so its
    label, readable at a glance.
    """
    rules = []
    for key, width, colour in zip(panels, widths, colours, strict=True):
        red, green, blue = (int(colour.lstrip("#")[j : j + 2], 16) for j in (0, 2, 4))
        rules += [
            f".st-key-{key}{{display:grid !important;grid-template-columns:repeat({width},minmax(0,1fr));"
            "gap:0.5rem;align-content:start;max-height:calc(100vh - 16rem);overflow-y:auto;padding:0.5rem;"
            f"background:rgba({red},{green},{blue},0.06) !important;border:2px solid {colour};"
            "border-top:none;border-radius:0 0 0.5rem 0.5rem;}",
            f".st-key-head-{key}{{background:rgba({red},{green},{blue},0.18);border:2px solid {colour};"
            "border-radius:0.5rem 0.5rem 0 0;padding:0.4rem 0.75rem;margin-bottom:-1rem;}",
            f".st-key-head-{key} {ICON}{{color:{colour};}}",
        ]
    st.html(
        "<style>"
        + "".join(rules)
        + f'[class*="st-key-{hints_prefix}"]{{grid-column:1/-1;min-height:8rem;justify-content:center;'
        "border:2px dashed rgba(128,128,128,0.4);border-radius:0.5rem;align-items:center;}</style>"
    )


def slots(counts: list[int], total: int) -> list[int]:
    """Share `total` columns out over panels in proportion to their counts: at least one each, summing up."""
    total = max(total, len(counts))
    weights = [max(count, 1) for count in counts]
    shares = [total * weight / sum(weights) for weight in weights]
    given = [max(1, int(share)) for share in shares]
    while sum(given) > total:
        given[max((i for i in range(len(given)) if given[i] > 1), key=lambda i: given[i])] -= 1
    for i in sorted(range(len(given)), key=lambda i: given[i] - shares[i])[: total - sum(given)]:
        given[i] += 1
    return given


def label_icon(label: Label) -> str:
    """Return the label's Material Symbols icon as markdown; by default chosen from its grade."""
    if label.icon:
        name = label.icon
    elif label.grade is None:
        name = "question_mark"
    else:
        name = "close" if label.grade <= 0 else "check" if label.grade == 1 else "done_all"
    return f":material/{name}:"


def _text_on(colour: str) -> str:
    # Black or white text, whichever contrasts better with the label colour (WCAG relative luminance).
    channels = [int(colour.lstrip("#")[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    r, g, b = (c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels)
    return "#000000" if 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.179 else "#FFFFFF"


def labels(labels: list[Label]) -> None:
    """Colour the label buttons, image frames and the adjudication control in the study's label colours.

    The buttons of one control join into one bar. An unselected button has a pale tint of its label colour and
    the icon in that colour; the selected one is filled with it. A judged image gets a frame and a tint in its
    label's colour: its container key ends in `lab<index>` (components/images.py).
    """
    last = len(labels) - 1
    rules = [
        '[class*="-labels"] [class*="-lbl"] button{border-radius:0;margin-left:-1px;white-space:nowrap;}',
        '[class*="st-key-group-"][class*="-labels"],[class*="st-key-group-"][class*="-labels"] button,'
        '[class*="st-key-sugbar-"][class*="-labels"],[class*="st-key-sugbar-"][class*="-labels"] button'
        "{flex-shrink:0 !important;}",
        '[class*="st-key-sugbar-"][class*="-labels"]{flex-wrap:nowrap !important;}',
        '[class*="-labels"] button *{overflow:visible !important;text-overflow:clip !important;}',
        '[class*="-labels"] [class*="-lbl0"] button{border-radius:6px 0 0 6px;margin-left:0;}',
        f'[class*="-labels"] [class*="-lbl{last}"] button{{border-radius:0 6px 6px 0;}}',
        '[class*="-labels"] [class*="-compare"]{margin-left:0.5rem;}',
    ]
    icon = ICON
    for i, label in enumerate(labels):
        red, green, blue = (int(label.colour.lstrip("#")[j : j + 2], 16) for j in (0, 2, 4))
        selected = (
            f"{{background-color:{label.colour} !important;border-color:{label.colour} !important;"
            f"color:{_text_on(label.colour)} !important;}}"
        )
        tint = (
            f"background-color:rgba({red},{green},{blue},0.10);border-color:rgba({red},{green},{blue},0.35);"
        )
        rules += [
            f'[class*="-lbl{i}"] button[kind="primary"]{selected}',
            f'[class*="-lbl{i}"] button[kind="secondary"]{{{tint}}}',
            # The group bar: icon in the label colour, name stays dark. Under each image the icon is the text.
            f'[class*="-lbl{i}"] button[kind="secondary"] {icon}{{color:{label.colour};}}',
            f'[class*="st-key-item-"][class*="-lbl{i}"] button[kind="secondary"],'
            f'[class*="st-key-review-"][class*="-lbl{i}"] button[kind="secondary"]{{color:{label.colour};}}',
            f'[class*="-lab{i}"] [data-testid="stImage"] img'
            f"{{box-shadow:0 0 0 3px {label.colour};border-radius:0.5rem;}}",
            # A tint over the judged image, as strong as "Tint judged" sets it (`tint_judged`).
            f'[class*="-lab{i}"] [data-testid="stImage"]{{position:relative;}}'
            f'[class*="-lab{i}"] [data-testid="stImage"]::after{{content:"";position:absolute;inset:0;'
            f"border-radius:0.5rem;pointer-events:none;"
            f"background:rgba({red},{green},{blue},var(--cara-tint,0.3));}}",
            # Suggest mode: the suggested label's button has a dashed outline, like the suggested images.
            f'[class*="-lbl{i}"][class*="-sugpick"] button'
            f"{{outline:2px dashed {label.colour};outline-offset:2px;}}",
            # Suggest mode: a dashed frame in the suggested label's colour, not yet a label.
            f'[class*="-sug{i}"] [data-testid="stImage"] img'
            f"{{outline:3px dashed {label.colour};outline-offset:-3px;border-radius:0.5rem;}}",
            f'[class*="st-key-adjudicate-"] button:nth-child({i + 1})[data-selected="true"]{selected}',
        ]
    rules.append(
        # Suggest mode's legend: one dashed swatch per kind of suggestion.
        '[class*="-nosug"] [data-testid="stImage"] img'
        "{outline:3px dashed #A1A1AA;outline-offset:-3px;border-radius:0.5rem;}"
        ".cara-legend{margin:0 0 0.25rem 0;padding-left:1.1rem;line-height:1.9;}"
        ".cara-swatch{display:inline-block;width:1.1rem;height:0.8rem;margin-right:0.5rem;"
        "vertical-align:-0.05rem;border:2px dashed;border-radius:0.2rem;}"
    )
    st.html("<style>" + "".join(rules) + "</style>")
