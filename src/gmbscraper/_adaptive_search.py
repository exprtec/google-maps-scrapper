from __future__ import annotations

import contextlib
import math
import re
from collections.abc import Callable
from typing import Any, Protocol

from playwright.sync_api import Error as PlaywrightError

from gmbscraper.models import MapsSearchLink, MapsView, SearchWindow

GOOGLE_MAPS_QUERY_RESULT_LIMIT = 120
SATURATED_RESULT_COUNT = 110
MAX_ADAPTIVE_DEPTH = 3
MAX_ADAPTIVE_WINDOWS = 220
MAX_SPLIT_ZOOM = 17
MAP_VIEWPORT_WIDTH = 1366
MAP_VIEWPORT_HEIGHT = 900
# Roughly a town plus its surroundings; Google often zooms seed results out to a region.
LOCAL_SEARCH_ZOOM = 12
PIN_PATTERN = re.compile(r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)")


class SearchScraper(Protocol):
    def new_page(self) -> Any: ...
    def open_search(self, page: Any, query: str) -> None: ...
    def open_search_at(
        self, page: Any, query: str, *, lat: float, lng: float, zoom: int
    ) -> None: ...
    def collect_place_links(self, page: Any, limit: int) -> list[tuple[str, str]]: ...


def collect_links_for_geo(
    *,
    scraper: SearchScraper,
    query: str,
    latitude: float | None = None,
    longitude: float | None = None,
    zoom: int | None = None,
    log: Callable[[str], None] | None = None,
) -> list[MapsSearchLink]:
    """Search a query and, if results saturate Google's ~120 cap, recursively
    split the viewport into quadrants to pull results beyond that cap.
    """
    seed_links, seed_view = _collect_seed_links(scraper, query)
    seen: set[str] = set()
    links: list[MapsSearchLink] = []
    _add_unique_links(links, seen, seed_links, keep_search_rank=True)
    if log:
        log(f"seed found={len(seed_links)} total={len(links)}")
    if len(seed_links) < SATURATED_RESULT_COUNT:
        return links

    root_view = _root_view(seed_view, latitude=latitude, longitude=longitude, zoom=zoom)
    if root_view is None:
        if log:
            log("missing search bounds; seed query only")
        return links

    max_depth = _max_adaptive_depth(root_view.zoom)
    if log:
        seed_zoom = f"z{seed_view.zoom}" if seed_view else "none"
        log(
            f"seed saturated; splitting z{root_view.zoom} around "
            f"{root_view.lat:.4f},{root_view.lng:.4f} (seed view {seed_zoom}, max depth {max_depth})"
        )
    queue: list[tuple[int, SearchWindow]] = [
        (1, window)
        for window in _split_window(
            _search_window_from_view(root_view, label="root"),
            next_zoom=root_view.zoom + 1,
        )
    ]
    searched = 1
    while queue and searched < MAX_ADAPTIVE_WINDOWS:
        depth, window = queue.pop(0)
        searched += 1
        page = scraper.new_page()
        # A window that fails to load is skipped rather than losing the whole search.
        try:
            scraper.open_search_at(
                page,
                query,
                lat=window.center_lat,
                lng=window.center_lng,
                zoom=window.zoom,
            )
            window_links = scraper.collect_place_links(page, GOOGLE_MAPS_QUERY_RESULT_LIMIT)
        except PlaywrightError as exc:
            if log:
                log(f"adaptive d{depth} z{window.zoom} {window.label} skipped: {exc}")
            continue
        finally:
            page.close()
        added = _add_unique_links(links, seen, window_links, keep_search_rank=False)
        if log:
            log(
                f"adaptive d{depth} z{window.zoom} {window.label} "
                f"found={len(window_links)} new={added} total={len(links)}"
            )
        if _should_split_window(window_links, depth=depth, zoom=window.zoom, max_depth=max_depth):
            queue.extend(
                (depth + 1, child) for child in _split_window(window, next_zoom=window.zoom + 1)
            )
    return links


def locate_area(scraper: SearchScraper, query: str) -> MapsView | None:
    """Resolve a place name to its map pin and the zoom Google frames it at."""
    page = scraper.new_page()
    try:
        scraper.open_search(page, query)
        with contextlib.suppress(Exception):
            page.wait_for_url(PIN_PATTERN, timeout=10000)
        pin = PIN_PATTERN.search(page.url)
        view = _parse_maps_view(page.url)
    finally:
        page.close()
    if pin is None or view is None:
        return None
    return MapsView(lat=float(pin.group(1)), lng=float(pin.group(2)), zoom=view.zoom)


def _root_view(
    seed_view: MapsView | None,
    *,
    latitude: float | None,
    longitude: float | None,
    zoom: int | None,
) -> MapsView | None:
    """Split around the caller's location, never wider than its area or the seed view."""
    if latitude is None or longitude is None:
        return seed_view
    area_zoom = zoom or LOCAL_SEARCH_ZOOM
    if seed_view is not None:
        area_zoom = max(area_zoom, seed_view.zoom)
    return MapsView(lat=latitude, lng=longitude, zoom=area_zoom)


def _max_adaptive_depth(root_zoom: int) -> int:
    zoom_headroom = max(0, MAX_SPLIT_ZOOM - root_zoom)
    return min(zoom_headroom, MAX_ADAPTIVE_DEPTH)


def _should_split_window(
    window_links: list[tuple[str, str]],
    *,
    depth: int,
    zoom: int,
    max_depth: int,
) -> bool:
    if len(window_links) < SATURATED_RESULT_COUNT:
        return False
    if depth >= max_depth:
        return False
    return zoom < MAX_SPLIT_ZOOM


def _collect_seed_links(
    scraper: SearchScraper, query: str
) -> tuple[list[tuple[str, str]], MapsView | None]:
    page = scraper.new_page()
    try:
        scraper.open_search(page, query)
        links = scraper.collect_place_links(page, GOOGLE_MAPS_QUERY_RESULT_LIMIT)
        return links, _parse_maps_view(page.url)
    finally:
        page.close()


def _add_unique_links(
    links: list[MapsSearchLink],
    seen: set[str],
    new_links: list[tuple[str, str]],
    *,
    keep_search_rank: bool,
) -> int:
    added = 0
    for search_position, (maps_url, fallback_name) in enumerate(new_links, start=1):
        if maps_url in seen:
            continue
        seen.add(maps_url)
        links.append(
            MapsSearchLink(
                maps_url=maps_url,
                fallback_name=fallback_name,
                search_rank=search_position if keep_search_rank else None,
            )
        )
        added += 1
    return added


def _parse_maps_view(url: str) -> MapsView | None:
    match = re.search(r"@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?),(\d+(?:\.\d+)?)z", url)
    if match is None:
        return None
    return MapsView(
        lat=float(match.group(1)),
        lng=float(match.group(2)),
        zoom=max(1, round(float(match.group(3)))),
    )


def _search_window_from_view(view: MapsView, *, label: str) -> SearchWindow:
    lat_span, lng_span = _viewport_span_degrees(view.lat, view.zoom)
    return SearchWindow(
        south=max(-85.0, view.lat - lat_span / 2),
        west=_normalize_lng(view.lng - lng_span / 2),
        north=min(85.0, view.lat + lat_span / 2),
        east=_normalize_lng(view.lng + lng_span / 2),
        zoom=view.zoom,
        label=label,
    )


def _viewport_span_degrees(center_lat: float, zoom: int) -> tuple[float, float]:
    world_pixels = 256 * (2**zoom)
    lat_rad = math.radians(_clamp(center_lat, -85.0, 85.0))
    meters_per_pixel = 156543.03392 * math.cos(lat_rad) / (2**zoom)
    width_m = MAP_VIEWPORT_WIDTH * meters_per_pixel
    height_m = MAP_VIEWPORT_HEIGHT * meters_per_pixel
    lat_span = height_m / 110_574
    lng_span = width_m / max(1.0, 111_320 * math.cos(lat_rad))
    if world_pixels <= 0:
        return 0.0, 0.0
    return max(lat_span, 0.001), max(lng_span, 0.001)


def _split_window(window: SearchWindow, *, next_zoom: int) -> list[SearchWindow]:
    mid_lat = (window.south + window.north) / 2
    mid_lng = (window.west + window.east) / 2
    return [
        SearchWindow(window.south, window.west, mid_lat, mid_lng, next_zoom, f"{window.label}.sw"),
        SearchWindow(window.south, mid_lng, mid_lat, window.east, next_zoom, f"{window.label}.se"),
        SearchWindow(mid_lat, window.west, window.north, mid_lng, next_zoom, f"{window.label}.nw"),
        SearchWindow(mid_lat, mid_lng, window.north, window.east, next_zoom, f"{window.label}.ne"),
    ]


def _normalize_lng(value: float) -> float:
    while value < -180:
        value += 360
    while value > 180:
        value -= 360
    return value


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(max(value, lower), upper)
