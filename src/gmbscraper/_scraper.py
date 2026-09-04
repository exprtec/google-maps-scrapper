from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from gmbscraper._adaptive_search import collect_links_for_geo
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
    OutletIdentity,
    PlaceProfile,
)

STEALTH_ARGS = ("--disable-blink-features=AutomationControlled",)
STEALTH_INIT_SCRIPT = "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
DEFAULT_VIEWPORT = {"width": 1366, "height": 900}


class GoogleMapsScraper:
    """A Playwright browser context wired up for scraping Google Maps."""

    def __init__(self, context: Any) -> None:
        self._context = context

    @property
    def context(self) -> Any:
        return self._context

    def new_page(self) -> Any:
        return self._context.new_page()

    def open_search(self, page: Any, query: str) -> None:
        open_search(page, query)

    def open_search_at(self, page: Any, query: str, *, lat: float, lng: float, zoom: int) -> None:
        open_search_at(page, query, lat=lat, lng=lng, zoom=zoom)

    def collect_place_links(self, page: Any, limit: int) -> list[tuple[str, str]]:
        return collect_place_links(page, limit)

    def scrape_place(
        self, place_url: str, *, fallback_name: str = "", rank: int = 1
    ) -> PlaceProfile:
        return scrape_place(self._context, place_url, fallback_name=fallback_name, rank=rank)

    def search_and_match(
        self,
        outlet: OutletIdentity,
        business: BusinessIdentity,
        *,
        max_candidates: int = 5,
        delay_range: tuple[float, float] = (0.8, 1.6),
    ) -> PlaceProfile | None:
        return search_and_match_place(
            self._context,
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
        log: Callable[[str], None] | None = None,
    ) -> list[MapsSearchLink]:
        """Search a query, automatically splitting the viewport into quadrants
        if results saturate Google's ~120-result cap.
        """
        return collect_links_for_geo(
            scraper=self, query=query, latitude=latitude, longitude=longitude, log=log
        )

    def scrape_reviews(self, maps_url: str, *, max_reviews: int | None = None) -> list[MapsReview]:
        page = self.new_page()
        try:
            return scrape_reviews_on_page(page, maps_url, max_reviews=max_reviews)
        finally:
            page.close()


@contextmanager
def google_maps_browser(
    *, headless: bool = True, locale: str = "en-AU"
) -> Iterator[GoogleMapsScraper]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless, args=list(STEALTH_ARGS))
        context = browser.new_context(
            locale=locale,
            viewport=DEFAULT_VIEWPORT,
            user_agent=DEFAULT_USER_AGENT,
        )
        context.add_init_script(STEALTH_INIT_SCRIPT)
        try:
            yield GoogleMapsScraper(context)
        finally:
            context.close()
            browser.close()
