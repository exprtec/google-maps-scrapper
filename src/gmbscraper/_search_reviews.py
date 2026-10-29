"""Read a place's reviews from Google Search's review panel.

Signed-out Google Maps now serves a "limited view" that shows only a handful of
reviews and asks the visitor to sign in for the rest. The review panel behind a
Search knowledge card (the "N Google reviews" link) still lists every review,
so the Maps scraper falls back to it for limited-view pages.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Collection
from typing import Any
from urllib.parse import quote_plus

from gmbscraper._page import accept_consent, evaluate_json
from gmbscraper.models import MapsReview
from gmbscraper.parsing import PLACE_ID_PATTERN, normalize_text, parse_relative_date

SEARCH_URL = "https://www.google.com/search?q={query}&hl={language}"
REVIEW_CARD = "div.bwb7ce"
REVIEW_PANE = "div.RVCQse"
IDLE_SCROLL_ROUNDS = 4
MAX_SCROLLS = 80

EXTRACT_SEARCH_REVIEWS_JS = """() => {
    // Filled stars are drawn in Google's gold; empty ones in a light grey.
    function countStars(card) {
        let filled = 0;
        for (const path of card.querySelectorAll('.h3PQJ svg path')) {
            const match = getComputedStyle(path).fill.match(/\\d+/g);
            if (match && Number(match[0]) > 200 && Number(match[2]) < 120) filled += 1;
        }
        return filled;
    }
    function reviewText(card) {
        // The full text sits in a hidden expanded copy; the visible one is truncated with "More".
        const node = card.querySelector('.gbdaZe .d83Iyc') || card.querySelector('.d83Iyc');
        if (!node) return '';
        const copy = node.cloneNode(true);
        copy.querySelectorAll('a[role="button"]').forEach((el) => el.remove());
        return (copy.textContent || '').trim().replace(/^["\\u201c]|["\\u201d]$/g, '').trim();
    }
    return [...document.querySelectorAll('div.bwb7ce')].map((card) => ({
        external_id: card.getAttribute('data-id')
            || card.querySelector('[data-review-id]')?.getAttribute('data-review-id') || '',
        username: (card.querySelector('.rhtdWc')?.textContent || '').trim(),
        stars: countStars(card),
        date_text: (card.querySelector('.y3Ibjb')?.textContent || '').trim(),
        text: reviewText(card),
    }));
}"""


def place_feature_id(url: str) -> str:
    """The `0x…:0x…` feature id Google uses for a place in Maps and Search URLs."""
    match = PLACE_ID_PATTERN.search(url or "")
    return match.group(1).lower() if match else ""


# Clicks are dispatched in the page: Search's layout often lays an overlay over
# these controls, which makes a pointer click time out.
CLICK_REVIEWS_LINK_JS = """(featureId) => {
    const pattern = /^\\s*[\\d,.]+\\s+Google reviews?\\s*$/i;
    const links = [...document.querySelectorAll('a[data-fid]')].filter((a) =>
        a.getAttribute('data-fid').toLowerCase() === featureId && pattern.test(a.textContent || ''));
    if (!links.length) return false;
    links[0].scrollIntoView({block: 'center'});
    links[0].click();
    return true;
}"""

CLICK_NEWEST_JS = """() => {
    const label = [...document.querySelectorAll('span, div, button')]
        .find((el) => el.children.length === 0 && (el.textContent || '').trim() === 'Newest');
    if (!label) return false;
    (label.closest('[jsaction], [role="button"], [role="radio"], [role="tab"]') || label).click();
    return true;
}"""


def open_search_review_panel(
    page: Any, *, name: str, feature_id: str, language: str = "en"
) -> bool:
    """Open the review panel for `feature_id` from a Search for `name`. False if
    Search doesn't show that place's review link (a name search can surface a
    different business, so only a link carrying the same feature id counts)."""
    if not feature_id:
        return False
    page.goto(
        SEARCH_URL.format(query=quote_plus(name), language=language),
        wait_until="domcontentloaded",
        timeout=45000,
    )
    accept_consent(page)
    with contextlib.suppress(Exception):
        page.wait_for_selector(f'a[data-fid="{feature_id}"]', timeout=10000)
    for _ in range(2):
        try:
            if not page.evaluate(CLICK_REVIEWS_LINK_JS, feature_id):
                return False
            page.wait_for_selector(REVIEW_CARD, timeout=15000)
            return True
        except Exception:
            continue
    return False


def sort_search_reviews_newest(page: Any) -> bool:
    try:
        first_id = page.locator(REVIEW_CARD).first.get_attribute("data-id")
        if not page.evaluate(CLICK_NEWEST_JS):
            return False
        # The list re-renders in place; wait for a different first card.
        page.wait_for_function(
            "([selector, id]) => { const c = document.querySelector(selector);"
            " return c && c.getAttribute('data-id') !== id; }",
            arg=[REVIEW_CARD, first_id],
            timeout=8000,
        )
        page.wait_for_timeout(500)
        return True
    except Exception:
        return False


def read_search_reviews(page: Any) -> list[MapsReview]:
    reviews: list[MapsReview] = []
    for item in evaluate_json(page, EXTRACT_SEARCH_REVIEWS_JS):
        stars = int(item.get("stars") or 0)
        if not 1 <= stars <= 5:
            continue
        date_text = normalize_text(item.get("date_text", ""))
        reviews.append(
            MapsReview(
                external_id=normalize_text(item.get("external_id", "")),
                stars=stars,
                username=normalize_text(item.get("username", "")),
                text=normalize_text(item.get("text", "")),
                date_text=date_text,
                date=parse_relative_date(date_text),
            )
        )
    return reviews


def _scroll_pane(page: Any) -> None:
    with contextlib.suppress(Exception):
        page.evaluate(
            "(selector) => { const el = document.querySelector(selector); if (el) el.scrollTop = el.scrollHeight; }",
            REVIEW_PANE,
        )


def scrape_search_reviews_on_page(
    page: Any,
    *,
    name: str,
    feature_id: str,
    max_reviews: int | None = None,
    known_ids: Collection[str] = (),
) -> list[MapsReview] | None:
    """Reviews newest first, or None when Search can't show this place's review panel."""
    if not name or not open_search_review_panel(page, name=name, feature_id=feature_id):
        return None
    sort_search_reviews_newest(page)

    seen: dict[str, MapsReview] = {}
    idle_rounds = 0
    for _ in range(MAX_SCROLLS):
        before = len(seen)
        reached_known = False
        for review in read_search_reviews(page):
            external_id = review.resolved_external_id()
            seen.setdefault(external_id, review)
            reached_known = reached_known or external_id in known_ids
        if reached_known or (max_reviews is not None and len(seen) >= max_reviews):
            break
        idle_rounds = idle_rounds + 1 if len(seen) == before else 0
        if idle_rounds >= IDLE_SCROLL_ROUNDS:
            break
        _scroll_pane(page)
        page.wait_for_timeout(900)
        time.sleep(0.2)

    reviews = list(seen.values())
    return reviews if max_reviews is None else reviews[:max_reviews]
