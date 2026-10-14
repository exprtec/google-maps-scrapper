from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from typing import Any
from uuid import uuid4

import psutil

from gmbscraper._adaptive_search import collect_links_for_geo, locate_area
from gmbscraper._page import open_page
from gmbscraper._places import (
    collect_place_links,
    open_search,
    open_search_at,
    scrape_place,
    search_and_match_place,
)
from gmbscraper._reviews import scrape_reviews_on_page
from gmbscraper.models import (
    BusinessIdentity,
    MapsReview,
    MapsSearchLink,
    MapsView,
    OutletIdentity,
    PlaceProfile,
)

STEALTH_ARGS = ("--disable-blink-features=AutomationControlled",)
# Skips decoding images, including inline ones that URL blocking can't catch.
LIGHTWEIGHT_ARGS = ("--blink-settings=imagesEnabled=false",)
STEALTH_INIT_SCRIPT = "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
DEFAULT_VIEWPORT = {"width": 1366, "height": 900}
BROWSER_MARKER_ENV = "GMBSCRAPER_BROWSER"


class BrowserStalledError(RuntimeError):
    """A scraper call made no progress within `stall_timeout`, so its browser was killed."""


class GoogleMapsScraper:
    """A Playwright browser context wired up for scraping Google Maps."""

    def __init__(self, context: Any) -> None:
        self._context = context

    @property
    def context(self) -> Any:
        return self._context

    @contextmanager
    def _step(self) -> Iterator[None]:
        yield

    def new_page(self) -> Any:
        with self._step():
            return open_page(self.context)

    def open_search(self, page: Any, query: str) -> None:
        with self._step():
            open_search(page, query)

    def open_search_at(self, page: Any, query: str, *, lat: float, lng: float, zoom: int) -> None:
        with self._step():
            open_search_at(page, query, lat=lat, lng=lng, zoom=zoom)

    def collect_place_links(self, page: Any, limit: int) -> list[tuple[str, str]]:
        with self._step():
            return collect_place_links(page, limit)

    def scrape_place(
        self, place_url: str, *, fallback_name: str = "", rank: int = 1
    ) -> PlaceProfile:
        with self._step():
            return scrape_place(self.context, place_url, fallback_name=fallback_name, rank=rank)

    def search_and_match(
        self,
        outlet: OutletIdentity,
        business: BusinessIdentity,
        *,
        max_candidates: int = 5,
        delay_range: tuple[float, float] = (0.8, 1.6),
    ) -> PlaceProfile | None:
        with self._step():
            return search_and_match_place(
                self.context,
                outlet,
                business,
                max_candidates=max_candidates,
                delay_range=delay_range,
            )

    def search_places_adaptive(
        self,
        query: str,
        *,
        latitude: float | None = None,
        longitude: float | None = None,
        zoom: int | None = None,
        log: Callable[[str], None] | None = None,
    ) -> list[MapsSearchLink]:
        """Search a query, automatically splitting the viewport into quadrants
        if results saturate Google's ~120-result cap.

        Pass the location's coordinates (and `zoom` from `locate`) to keep
        splitting within that area instead of Google's often region-wide view.
        """
        with self._step():
            return collect_links_for_geo(
                scraper=self,
                query=query,
                latitude=latitude,
                longitude=longitude,
                zoom=zoom,
                log=log,
            )

    def locate(self, query: str) -> MapsView | None:
        """Geocode a place name such as "Amberley, NZ" with Google Maps."""
        with self._step():
            return locate_area(self, query)

    def scrape_reviews(self, maps_url: str, *, max_reviews: int | None = None) -> list[MapsReview]:
        with self._step():
            page = self.new_page()
            try:
                return scrape_reviews_on_page(page, maps_url, max_reviews=max_reviews)
            finally:
                page.close()


class _Browser:
    """One Chromium launch whose processes any thread can kill."""

    def __init__(self, playwright: Any, *, headless: bool, locale: str) -> None:
        self._marker = uuid4().hex
        self._browser = playwright.chromium.launch(
            headless=headless,
            args=[*STEALTH_ARGS, *LIGHTWEIGHT_ARGS],
            env={**os.environ, BROWSER_MARKER_ENV: self._marker},
        )
        self.context = self._browser.new_context(
            locale=locale,
            viewport=DEFAULT_VIEWPORT,
            user_agent=DEFAULT_USER_AGENT,
        )
        self.context.add_init_script(STEALTH_INIT_SCRIPT)

    def close(self) -> None:
        # A killed browser rejects close calls; there is nothing left to clean up.
        with suppress(Exception):
            self.context.close()
        with suppress(Exception):
            self._browser.close()

    def kill(self) -> None:
        for process in psutil.Process().children(recursive=True):
            with suppress(psutil.Error):
                if process.environ().get(BROWSER_MARKER_ENV) == self._marker:
                    process.kill()


class _StallGuardedScraper(GoogleMapsScraper):
    """Kills a browser whose call stops progressing and relaunches it for the next call."""

    def __init__(self, launch: Callable[[], _Browser], stall_timeout: float) -> None:
        self._launch = launch
        self._browser = launch()
        self._stall_timeout = stall_timeout
        self._depth = 0
        self._last_progress = time.monotonic()
        self._stalled = False
        self._closed = threading.Event()
        threading.Thread(target=self._watch, daemon=True).start()

    @property
    def context(self) -> Any:
        return self._browser.context

    def close(self) -> None:
        self._closed.set()
        self._browser.close()

    @contextmanager
    def _step(self) -> Iterator[None]:
        if self._depth == 0 and self._stalled:
            self._browser.close()
            self._browser = self._launch()
            self._stalled = False
        self._depth += 1
        self._last_progress = time.monotonic()
        try:
            yield
        except Exception as exc:
            if self._stalled and not isinstance(exc, BrowserStalledError):
                raise self._stall_error() from exc
            raise
        finally:
            self._depth -= 1
            self._last_progress = time.monotonic()
        if self._stalled:
            raise self._stall_error()

    def _stall_error(self) -> BrowserStalledError:
        return BrowserStalledError(
            f"browser made no progress for {self._stall_timeout:.0f}s and was killed"
        )

    def _watch(self) -> None:
        interval = min(30.0, self._stall_timeout / 4)
        while not self._closed.wait(interval):
            idle = time.monotonic() - self._last_progress
            if self._depth and not self._stalled and idle > self._stall_timeout:
                self._stalled = True
                self._browser.kill()


@contextmanager
def google_maps_browser(
    *, headless: bool = True, locale: str = "en-AU", stall_timeout: float | None = None
) -> Iterator[GoogleMapsScraper]:
    """Open a Google Maps scraper.

    With `stall_timeout`, a call that makes no progress for that many seconds has
    its browser killed and raises `BrowserStalledError`; the next call relaunches it.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:

        def launch() -> _Browser:
            return _Browser(playwright, headless=headless, locale=locale)

        if stall_timeout is None:
            browser = launch()
            try:
                yield GoogleMapsScraper(browser.context)
            finally:
                browser.close()
            return
        scraper = _StallGuardedScraper(launch, stall_timeout)
        try:
            yield scraper
        finally:
            scraper.close()
