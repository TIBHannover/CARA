"""What the pages share within a session (login, open study, browser cookies) and across sessions
(thumbnails)."""

import json
import os
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

import streamlit as st

from client import CaraClient, Study

API_URL = os.environ.get("CARA_API_URL", "http://localhost:8000")
ThumbKey = tuple[str, int, int, int, bool]


def remember(**values: str | None) -> None:
    """Queue browser cookies to write on this run (None deletes one).

    A reload starts a new Streamlit session; the cookies let it log the person back in and reopen their study
    (`main.restore_session`).
    """
    st.session_state.setdefault("cookie_writes", {}).update(values)


def write_cookies() -> None:
    """Write the cookies queued by `remember` with a small script on the page."""
    # Session cookies (gone when the browser closes), sent only to this site. Not HttpOnly: Streamlit can only
    # set them from the page. The login token in them expires on the server anyway (CARA_TOKEN_MINUTES).
    writes: dict[str, str | None] = st.session_state.pop("cookie_writes", {})
    if writes:
        script = "".join(
            f"document.cookie = {json.dumps(f'{name}={value or ""}; path=/; SameSite=Strict')}"
            + (" + '; max-age=0'" if value is None else "")
            + ";"
            for name, value in writes.items()
        )
        st.html(f"<script>{script}</script>", unsafe_allow_javascript=True)


def client() -> CaraClient:
    """Return an API client with this session's login token."""
    return CaraClient(API_URL, st.session_state.token)


@st.cache_data(ttl="30s", max_entries=100, show_spinner=False)
def _study(token: str, study_id: int) -> Study:
    return CaraClient(API_URL, token).study(study_id)


def current_study() -> Study:
    """Return the open study, cached for 30 seconds; `forget_study` drops the cache after a change."""
    return _study(st.session_state.token, st.session_state.study_id)


def forget_study() -> None:
    """Drop the cached studies, so the next `current_study` reads the saved settings."""
    _study.clear()


class ThumbnailStore:
    """Thumbnails for every session, least recently used dropped first, with background pre-fetching.

    Safe to call from any thread. Keyed by login token, so an image is only served to the login that fetched
    it through the API, which checked that login's membership of the study. A new login fetches its images
    again.
    """

    def __init__(self, max_items: int) -> None:
        self._images: OrderedDict[ThumbKey, bytes] = OrderedDict()
        self._lock = threading.Lock()
        self._max_items = max_items
        self._fetch_pool = ThreadPoolExecutor(max_workers=16)
        self._background = ThreadPoolExecutor(max_workers=2)
        self._queued: set[tuple[int, int]] = set()

    def get(
        self, token: str, study_id: int, image_ids: list[int], size: int, square: bool
    ) -> dict[int, bytes]:
        """Return the images by id, fetching the missing ones in parallel with the caller's token."""
        keys = {image_id: (token, study_id, image_id, size, square) for image_id in image_ids}
        with self._lock:
            found = {i: self._images[k] for i, k in keys.items() if k in self._images}
            for key in (keys[i] for i in found):
                self._images.move_to_end(key)
        missing = [i for i in image_ids if i not in found]
        if missing:
            api = CaraClient(API_URL, token)
            fetched = dict(
                zip(
                    missing,
                    self._fetch_pool.map(lambda i: api.image(study_id, i, size, square), missing),
                    strict=True,
                )
            )
            with self._lock:
                for image_id, data in fetched.items():
                    self._images[keys[image_id]] = data
                while len(self._images) > self._max_items:
                    self._images.popitem(last=False)
            found |= fetched
        return found

    def prefetch_query(self, token: str, study_id: int, query_id: int, thumb_px: int, query_px: int) -> None:
        """Fetch a query's images in the background, so opening it next doesn't wait.

        Best effort: a failed prefetch is dropped, and opening the query fetches the images again.
        """
        with self._lock:
            if (study_id, query_id) in self._queued:
                return
            self._queued.add((study_id, query_id))
        self._background.submit(self._prefetch, token, study_id, query_id, thumb_px, query_px)

    def _prefetch(self, token: str, study_id: int, query_id: int, thumb_px: int, query_px: int) -> None:
        try:
            view = CaraClient(API_URL, token).query(study_id, query_id)
            self.get(token, study_id, [m.image_id for m in view.members], thumb_px, True)
            if view.image_id is not None:
                self.get(token, study_id, [view.image_id], query_px, False)
        finally:
            with self._lock:
                self._queued.discard((study_id, query_id))


@st.cache_resource
def thumbnail_store() -> ThumbnailStore:
    """Return the one `ThumbnailStore` of this server process."""
    return ThumbnailStore(max_items=20_000)


def thumbnails(
    token: str, study_id: int, image_ids: tuple[int, ...], size: int, square: bool
) -> dict[int, bytes]:
    """Return thumbnails by id, from the shared `ThumbnailStore`."""
    return thumbnail_store().get(token, study_id, list(image_ids), size, square)
