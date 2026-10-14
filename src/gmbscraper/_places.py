from __future__ import annotations

import contextlib
import random
import time
from typing import Any
from urllib.parse import quote_plus

from gmbscraper._matching import is_definitive_match, match_place, pick_best_match
from gmbscraper._page import (
    accept_consent,
    first_attr,
    first_text,
    open_page,
    read_aggregate_review_count,
    resolve_maps_place_url,
    scroll_search_results,
    wait_for_content,
)
from gmbscraper.models import BusinessIdentity, OutletIdentity, PlaceProfile
from gmbscraper.parsing import (
    extract_lat_lng,
    extract_place_id,
    is_generic_search_heading,
    normalize_text,
    parse_decimal,
)

UNLIMITED_SEARCH_SCROLL_LIMIT = 1000
# Upper bound on waiting for a page's content to render after navigation.
CONTENT_MAX_WAIT_MS = 5000
SEARCH_CONTENT_SELECTORS = ('div[role="feed"], h1.DUwDvf',)
PLACE_CONTENT_SELECTORS = ("h1.DUwDvf", "[data-item-id]")

COLLECT_PLACE_LINKS_JS = """() => {
    const feed = document.querySelector('div[role="feed"]');
    if (!feed) return [];
    return Array.from(feed.querySelectorAll('a[href*="/maps/place/"]'))
        .map((anchor) => {
            let name = (anchor.getAttribute('aria-label') || '').trim();
            if (!name) {
                const card = anchor.closest('div[role="article"]') || anchor.parentElement;
                const nameEl = card?.querySelector('.qBF1Pd, .fontHeadlineSmall');
                name = (nameEl?.textContent || anchor.textContent || '').trim();
            }
            return { href: anchor.href || '', name };
        });
}"""

SEARCH_RESULTS_SETTLED_JS = """(knownCount) => {
    const feed = document.querySelector('div[role="feed"]');
    if (!feed) return true;
    const hrefs = new Set(
        Array.from(feed.querySelectorAll('a[href*="/maps/place/"]'))
            .map((anchor) => anchor.href || '')
            .filter((href) => href && !href.includes('/maps/search/'))
    );
    const text = (feed.innerText || '').toLowerCase();
    const atEnd = [
        "you've reached the end of the list",
        "you have reached the end of the list",
        "end of the list",
    ].some((phrase) => text.includes(phrase));
    return hrefs.size > knownCount || atEnd;
}"""


def open_search(page: Any, query: str) -> None:
    url = f"https://www.google.com/maps/search/{quote_plus(query)}"
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    accept_consent(page)
    wait_for_content(page, SEARCH_CONTENT_SELECTORS, max_wait_ms=CONTENT_MAX_WAIT_MS)


def open_search_at(page: Any, query: str, *, lat: float, lng: float, zoom: int) -> None:
    url = f"https://www.google.com/maps/search/{quote_plus(query)}/@{lat:.6f},{lng:.6f},{zoom}z"
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    accept_consent(page)
    wait_for_content(page, SEARCH_CONTENT_SELECTORS, max_wait_ms=CONTENT_MAX_WAIT_MS)


def wait_for_search_results_to_settle(page: Any, known_count: int) -> None:
    try:
        page.wait_for_function(SEARCH_RESULTS_SETTLED_JS, arg=known_count, timeout=5000)
    except Exception:
        page.wait_for_timeout(1500)


def collect_place_links(page: Any, limit: int) -> list[tuple[str, str]]:
    if "/maps/place/" in page.url:
        name = first_text(page, ("h1.DUwDvf", "h1"))
        return [(page.url, name)]

    detail_name = first_text(page, ("h1.DUwDvf", "h1"))
    if detail_name and not is_generic_search_heading(detail_name):
        with contextlib.suppress(Exception):
            page.wait_for_url("**/maps/place/**", timeout=5000)
        if "/maps/place/" in page.url:
            return [(page.url, detail_name)]

    with contextlib.suppress(Exception):
        page.wait_for_selector('div[role="feed"]', timeout=10000)

    seen: set[str] = set()
    results: list[tuple[str, str]] = []
    unlimited = limit <= 0
    max_scrolls = UNLIMITED_SEARCH_SCROLL_LIMIT if unlimited else max(8, min(1000, limit * 4))
    stalled_scrolls = 0
    for _ in range(max_scrolls):
        before_count = len(results)
        try:
            items = page.evaluate(COLLECT_PLACE_LINKS_JS)
        except Exception:
            items = []
        for item in items:
            href = normalize_text((item or {}).get("href", ""))
            name = normalize_text((item or {}).get("name", ""))
            if (
                not href
                or "/maps/place/" not in href
                or "/maps/search/" in href
                or href in seen
                or is_generic_search_heading(name)
            ):
                continue
            seen.add(href)
            results.append((href, name))
            if not unlimited and len(results) >= limit:
                return results
        if len(results) == before_count:
            stalled_scrolls += 1
        else:
            stalled_scrolls = 0
        if stalled_scrolls >= 10:
            return results
        known_count = len(seen)
        scroll_state = scroll_search_results(page)
        wait_for_search_results_to_settle(page, known_count)
        if scroll_state["at_end"] and len(results) == before_count:
            return results
    return results


def scrape_place(
    context: Any,
    place_url: str,
    *,
    fallback_name: str = "",
    rank: int = 1,
) -> PlaceProfile:
    page = open_page(context)
    place = PlaceProfile(
        rank=rank,
        name=normalize_text(fallback_name),
        maps_url=place_url,
        place_id=extract_place_id(place_url),
    )
    try:
        page.goto(place_url, wait_until="domcontentloaded", timeout=40000)
        accept_consent(page)
        wait_for_content(page, PLACE_CONTENT_SELECTORS, max_wait_ms=CONTENT_MAX_WAIT_MS)
        maps_url = resolve_maps_place_url(page, place_url)
        lat, lng = extract_lat_lng(maps_url)
        place.name = first_text(page, ("h1.DUwDvf", "h1")) or place.name
        place.category = first_text(
            page,
            ("button.DkEaL", "button[jsaction*='pane.rating.category']"),
        )
        place.address = first_text(
            page,
            (
                "button[data-item-id='address'] .fontBodyMedium",
                "button[data-item-id='address']",
            ),
        )
        place.phone = first_text(
            page,
            (
                "button[data-item-id^='phone:tel:'] .fontBodyMedium",
                "button[data-item-id^='phone:tel:']",
            ),
        )
        place.website = first_attr(
            page,
            ("a[data-item-id='authority']", "a[aria-label*='Website']"),
            "href",
        )
        place.rating = parse_decimal(
            first_text(
                page,
                ("div.F7nice span[aria-hidden='true']", "span[aria-label*='stars']"),
            )
        )
        place.review_count = read_aggregate_review_count(page)
        place.maps_url = maps_url
        place.place_id = place.place_id or extract_place_id(maps_url)
        place.lat = lat
        place.lng = lng
    except Exception:
        pass
    finally:
        page.close()
    return place


def search_and_match_place(
    context: Any,
    outlet: OutletIdentity,
    business: BusinessIdentity,
    *,
    max_candidates: int,
    delay_range: tuple[float, float] = (0.8, 1.6),
) -> PlaceProfile | None:
    query = f"{business.name} {outlet.address or ''}".strip()
    page = open_page(context)
    try:
        open_search(page, query)
        links = collect_place_links(page, max_candidates)
    finally:
        page.close()

    matches: list[PlaceProfile] = []
    for rank, (place_url, fallback_name) in enumerate(links, start=1):
        place = scrape_place(context, place_url, fallback_name=fallback_name, rank=rank)
        matched = match_place(place, outlet, business)
        if matched is not None:
            if is_definitive_match(matched):
                return matched
            matches.append(matched)
        time.sleep(random.uniform(*delay_range))
    return pick_best_match(matches)
