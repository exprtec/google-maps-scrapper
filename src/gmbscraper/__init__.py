"""Playwright-based scraper for Google Maps / Google Business Profile listings and reviews."""

from gmbscraper._matching import has_match_key, is_definitive_match, match_place, pick_best_match
from gmbscraper._parallel import chunk_items, run_chunked
from gmbscraper._reviews import GoogleReviewsUnavailableError, scrape_reviews
from gmbscraper._scraper import GoogleMapsScraper, google_maps_browser
from gmbscraper._version import __version__
from gmbscraper.models import (
    BusinessIdentity,
    MapsReview,
    MapsSearchLink,
    MapsView,
    OutletIdentity,
    PlaceProfile,
    SearchWindow,
)
from gmbscraper.parsing import normalize_text

__all__ = [
    "BusinessIdentity",
    "GoogleMapsScraper",
    "GoogleReviewsUnavailableError",
    "MapsReview",
    "MapsSearchLink",
    "MapsView",
    "OutletIdentity",
    "PlaceProfile",
    "SearchWindow",
    "__version__",
    "chunk_items",
    "google_maps_browser",
    "has_match_key",
    "is_definitive_match",
    "match_place",
    "normalize_text",
    "pick_best_match",
    "run_chunked",
    "scrape_reviews",
]
