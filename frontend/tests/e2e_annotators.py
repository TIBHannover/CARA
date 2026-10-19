"""Browser smoke test: several simulated annotators judge every assigned query of a study at the same time.

Each annotator logs in, judges each pool group by group (correcting single images where the ground truth
differs from the group's majority), finishes the review round and moves on with "Next query", exactly as a
person would. Afterwards every saved label is compared with what the annotator clicked.

    uv run --group e2e playwright install chromium        # once
    uv run --group e2e python tests/e2e_annotators.py 5 data/met_e2e/ground_truth.qrels ann1 ann2 ann3

Users must exist with their username as password and be assigned to the study. The first annotator also
splits mixed groups; the second flips 3% of labels; the third marks 3% as unsure. Exit code 1 on any problem.
"""

import argparse
import asyncio
import json
import random
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

from playwright.async_api import Browser, Page, async_playwright

QUIET = """() => !document.querySelector('[data-testid="stStatusWidget"]')?.innerText.match(/Running|Stop/)"""


class Annotator:
    """One simulated person in a browser of their own, with their clicks and the problems they ran into.

    `persona`: 0 also splits mixed groups, 1 flips 3% of labels, 2 marks 3% as unsure.
    """

    def __init__(self, args: argparse.Namespace, user: str, persona: int, positives: set[tuple[str, str]]):
        self.args, self.user, self.persona, self.positives = args, user, persona, positives
        self.problems: list[str] = []
        self.clicks = 0
        self.token = self._login_api()
        # The study's labels in button order; relevant, not relevant and unsure are found by their grade.
        labels = self.api("")["settings"]["labels"]
        self.names: list[str] = [label["name"] for label in labels]
        grade: dict[int | None, str] = {label["grade"]: label["name"] for label in labels}
        self.relevant, self.not_relevant, self.unsure = grade[1], grade[0], grade[None]

    def _login_api(self) -> str:
        data = urllib.parse.urlencode({"username": self.user, "password": self.user}).encode()
        token: str = json.load(urllib.request.urlopen(f"{self.args.api}/auth/token", data))["access_token"]
        return token

    def api(self, path: str) -> Any:
        """GET a path under the study from the API, as this user."""
        request = urllib.request.Request(
            f"{self.args.api}/studies/{self.args.study}{path}",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        return json.load(urllib.request.urlopen(request))

    def wanted(self, query: str, doc: str) -> str:
        """Return the label this annotator means to give: the ground truth, with their persona's errors."""
        relevant = (query, doc) in self.positives
        draw = random.Random(f"{self.user}{query}{doc}").random()
        if self.persona == 1 and draw < 0.03:
            relevant = not relevant
        if self.persona == 2 and draw < 0.03:
            return self.unsure
        return self.relevant if relevant else self.not_relevant

    async def settle(self, page: Page) -> None:
        """Wait until Streamlit has finished the current rerun."""
        await page.wait_for_timeout(150)
        await page.wait_for_function(QUIET, timeout=120_000)

    async def choose(self, page: Page, key: str, label: str) -> None:
        """Click `label` in the label bar `key`, unless it is already chosen, and wait for it to show."""
        index = self.names.index(label)
        selector = f".st-key-{key}-lbl{index} button"
        button = page.locator(selector).first
        if await button.get_attribute("kind") == "primary":
            return
        await button.click()
        self.clicks += 1
        try:
            await page.wait_for_function(
                f"document.querySelector('{selector}')?.getAttribute('kind') === 'primary'",
                timeout=60_000,
            )
        except Exception:
            self.problems.append(f"{self.user}: {key} did not show {label}")
        await self.settle(page)

    async def current_query(self, page: Page) -> int:
        """Return the id of the query on screen, read from the mode switch's key."""
        await page.locator('[class*="st-key-mode-"]').first.wait_for(timeout=120_000)
        await self.settle(page)
        key = await page.evaluate(
            """() => [...document.querySelector('[class*="st-key-mode-"]').classList]
                     .find(c => c.startsWith('st-key-mode-'))"""
        )
        return int(key.rsplit("-", 1)[1])

    def members(self, view: dict[str, Any]) -> list[dict[str, Any]]:
        """Return every pool image of a query view: the groups', then the ones judged alone."""
        grouped: list[dict[str, Any]] = [m for g in view["groups"] for m in g["members"]]
        return grouped + list(view["individual"])

    async def split(self, page: Page, query: int, ids: list[int], key: str) -> dict[str, Any]:
        """Split the group `ids` and return the query view once both halves are on the page."""
        button = page.locator(f".st-key-split-{key} button").first
        # Toasts and the sticky page header can sit on top of the button; Playwright's own scroll leaves it
        # under the header. A toast stays while the pointer rests on it, so the pointer moves away first.
        await page.mouse.move(20, 500)
        await page.locator('[data-testid="stToast"]').first.wait_for(state="detached", timeout=30_000)
        await button.evaluate("e => e.scrollIntoView({block: 'center'})")
        await button.click()
        self.clicks += 1
        for _ in range(100):
            view: dict[str, Any] = self.api(f"/queries/{query}")
            if not any(sorted(m["member_id"] for m in g["members"]) == sorted(ids) for g in view["groups"]):
                break
            await page.wait_for_timeout(100)
        for group in view["groups"]:
            half = [m["member_id"] for m in group["members"]]
            if set(half) < set(ids):
                await page.locator(f".st-key-group-{query}-{min(half)}-{len(half)}-labels").first.wait_for()
        await self.settle(page)
        return view

    async def judge(self, page: Page, query: int) -> None:
        """Judge a query group by group, correct single images, then check every saved label."""
        view: dict[str, Any] = self.api(f"/queries/{query}")
        external = view["external_id"]
        split_done: set[str] = set()
        restart = True
        while restart:
            restart = False
            for group in view["groups"]:
                ids = [m["member_id"] for m in group["members"]]
                want = {m["member_id"]: self.wanted(external, m["doc_id"]) for m in group["members"]}
                key = f"group-{query}-{min(ids)}-{len(ids)}"
                if (
                    self.persona == 0
                    and len(set(want.values())) > 1
                    and len(ids) >= 4
                    and key not in split_done
                ):
                    split_done.add(key)
                    view = await self.split(page, query, ids, key)
                    restart = True
                    break
                majority = Counter(want.values()).most_common(1)[0][0]
                await self.choose(page, key, majority)
                for member, label in want.items():
                    if label != majority:
                        await self.choose(page, f"item-{query}-{member}", label)
        for member in view["individual"]:
            await self.choose(
                page, f"item-{query}-{member['member_id']}", self.wanted(external, member["doc_id"])
            )
        for _ in range(20):  # the last click's save may still be in flight
            wrong = [
                m["doc_id"]
                for m in self.members(self.api(f"/queries/{query}"))
                if m["label"] != self.wanted(external, m["doc_id"])
            ]
            if not wrong:
                return
            await page.wait_for_timeout(500)
        self.problems.append(f"{self.user} query {query}: {len(wrong)} saved labels differ, e.g. {wrong[:3]}")

    async def close_dialog(self, page: Page) -> None:
        """Close the "All done" dialog if it is open."""
        dialog = page.get_by_role("dialog")
        if await dialog.count():
            await dialog.get_by_role("button", name="Back to my queries").click()
            await self.settle(page)

    async def review(self, page: Page, query: int) -> None:
        """Open Review mode and mark the query reviewed."""
        await self.close_dialog(page)
        await page.locator(f".st-key-mode-{query}").get_by_role("radio", name="Review").first.click()
        await self.settle(page)
        try:
            await page.get_by_role("button", name="Done reviewing").first.click(timeout=30_000)
            self.clicks += 1
            await page.get_by_text("Review done.").first.wait_for(timeout=30_000)
        except Exception:
            self.problems.append(f"{self.user} query {query}: could not finish the review")
        await self.close_dialog(page)

    async def run(self, browser: Browser) -> None:
        """Log in, open the study, and judge and review every assigned query with "Next query"."""
        page = await (await browser.new_context(viewport={"width": 1500, "height": 950})).new_page()
        page.on("pageerror", lambda error: self.problems.append(f"{self.user}: page error {error}"))
        await page.goto(self.args.ui)
        await page.get_by_label("Username").fill(self.user)
        await page.get_by_role("textbox", name="Password").fill(self.user)
        await page.get_by_role("button", name="Log in").click()
        await page.locator(f".st-key-open-{self.args.study} button").click()
        done: list[int] = []
        while True:
            query = await self.current_query(page)
            if query in done:
                self.problems.append(f"{self.user}: came back to finished query {query}")
                break
            await self.judge(page, query)
            await self.review(page, query)
            done.append(query)
            following = page.get_by_role("button", name="Next query").first
            if not await following.is_enabled():
                break
            await following.click()
            await page.wait_for_function(f"!document.querySelector('.st-key-mode-{query}')", timeout=30_000)
        queue = self.api("/queue")
        unfinished = [q["query_id"] for q in queue if q["judged"] < q["pool_size"] or not q["reviewed"]]
        if unfinished:
            self.problems.append(f"{self.user}: queries left unfinished: {unfinished}")
        print(f"{self.user}: {len(done)} queries, {self.clicks} clicks", flush=True)


async def main() -> None:
    """Run the annotators side by side and exit 1 if any of them ran into a problem."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("study", type=int)
    parser.add_argument("qrels", type=Path, help="ground truth: query_id 0 doc_id grade")
    parser.add_argument("users", nargs="+")
    parser.add_argument("--ui", default="http://localhost:8501")
    parser.add_argument("--api", default="http://localhost:8000")
    args = parser.parse_args()
    positives = {
        (fields[0], fields[2])
        for fields in map(str.split, args.qrels.read_text().splitlines())
        if fields and int(fields[3]) > 0
    }
    annotators = [Annotator(args, user, persona % 3, positives) for persona, user in enumerate(args.users)]
    started = time.perf_counter()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        await asyncio.gather(*(annotator.run(browser) for annotator in annotators))
        await browser.close()
    problems = [problem for annotator in annotators for problem in annotator.problems]
    print(f"{len(annotators)} annotators in {(time.perf_counter() - started) / 60:.1f} min")
    print("\n".join(problems) or "no problems")
    raise SystemExit(1 if problems else 0)


if __name__ == "__main__":
    asyncio.run(main())
