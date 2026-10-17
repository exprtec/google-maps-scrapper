from __future__ import annotations

import contextlib
import time
from collections.abc import Collection
from typing import Any

from gmbscraper._page import (
    click_reviews_tab,
    evaluate_json,
    is_limited_maps_view,
    navigate_to_place,
    open_page,
    scroll_reviews_pane,
    set_reviews_sort,
)
from gmbscraper.models import MapsReview
from gmbscraper.parsing import normalize_text, parse_relative_date

EXTRACT_REVIEWS_JS = """() => {
    function extractUsername(card) {
        const contribBtn = card.querySelector(
            'button[data-href*="/maps/contrib/"]:not([aria-label])'
        ) || card.querySelector('button[data-href*="/maps/contrib/"]');
        if (contribBtn) {
            const innerDiv = contribBtn.querySelector('div');
            const innerText = (innerDiv?.textContent || '').trim();
            if (innerText) return innerText;
            const aria = (contribBtn.getAttribute('aria-label') || '').trim();
            if (aria && !/photo|image|profile picture/i.test(aria)) return aria;
        }
        const profileLink = card.querySelector('a[href*="/maps/contrib/"]');
        if (profileLink) {
            const linkText = (profileLink.textContent || '').trim();
            if (linkText) return linkText;
        }
        for (const selector of [
            'div.d4r55',
            'button.WEBjve div',
            'a.WEBjve div',
            'button.WEBjve',
            'a.WEBjve',
            '[class*="d4r55"]',
        ]) {
            const el = card.querySelector(selector);
            const text = (el?.textContent || '').trim();
            if (text) return text;
        }
        return '';
    }

    function extractStars(card) {
        const starsEl = card.querySelector('span[role="img"][aria-label*="star"]')
            || card.querySelector('[aria-label*="stars"]');
        const starsLabel = (starsEl?.getAttribute('aria-label') || '').toLowerCase();
        const starsMatch = starsLabel.match(/(\\d)/);
        if (!starsMatch) return null;
        const stars = parseInt(starsMatch[1], 10);
        return stars >= 1 && stars <= 5 ? stars : null;
    }

    function extractDate(card) {
        for (const selector of ['span.rsqaWe', '[class*="rsqaWe"]']) {
            const text = (card.querySelector(selector)?.textContent || '').trim();
            if (text) return text;
        }
        return '';
    }

    function ownerResponseRoots(card) {
        const roots = new Set();
        for (const selector of [
            'div.CDeFdr',
            '[class*="CDeFdr"]',
            '[class*="CDe7pd"]',
            'div.PhqDud',
            '[class*="PhqDud"]',
            '[data-owner-response]',
        ]) {
            for (const el of card.querySelectorAll(selector)) {
                roots.add(el);
            }
        }
        for (const el of card.querySelectorAll('div, span, button')) {
            const text = (el.textContent || '').trim();
            if (!/^(Response from the owner|Owner response)$/i.test(text)) continue;
            let root = el.parentElement;
            for (let depth = 0; root && root !== card && depth < 6; depth += 1) {
                roots.add(root);
                root = root.parentElement;
            }
        }
        return roots;
    }

    function isInsideOwnerResponse(node, ownerRoots) {
        if (!node) return false;
        for (const root of ownerRoots) {
            if (root.contains(node)) return true;
        }
        return false;
    }

    function expandReviewText(card) {
        const reviewBody = card.querySelector('div.MyEned, [class*="MyEned"]');
        if (!reviewBody) return;
        reviewBody.querySelectorAll(
            'button[aria-label*="See more"], button[aria-label*="More"]'
        ).forEach((btn) => {
            try { btn.click(); } catch (_) {}
        });
    }

    function extractText(card) {
        const ownerRoots = ownerResponseRoots(card);
        const reviewBody = card.querySelector('div.MyEned, [class*="MyEned"]');
        if (reviewBody) {
            const el = reviewBody.querySelector('span.wiI7pd, [class*="wiI7pd"]');
            return (el?.textContent || '').trim();
        }
        for (const el of card.querySelectorAll('span.wiI7pd, [class*="wiI7pd"]')) {
            if (isInsideOwnerResponse(el, ownerRoots)) continue;
            const text = (el.textContent || '').trim();
            if (text) return text;
        }
        return '';
    }

    const results = [];
    const seen = new Set();
    const cards = document.querySelectorAll('div[data-review-id], div.jftiEf');
    for (const card of cards) {
        expandReviewText(card);
        const externalId = card.getAttribute('data-review-id') || '';
        const stars = extractStars(card);
        if (stars === null) continue;
        const username = extractUsername(card);
        const dateText = extractDate(card);
        const text = extractText(card);
        const key = externalId || `${username}|${stars}|${dateText}|${text.slice(0, 80)}`;
        if (seen.has(key)) continue;
        seen.add(key);
        results.push({
            external_id: externalId,
            stars,
            username,
            date_text: dateText,
            text,
        });
    }
    return results;
}"""


class GoogleReviewsUnavailableError(RuntimeError):
    pass


class GoogleLimitedViewError(GoogleReviewsUnavailableError):
    """Google served its signed-out limited view, which has no reviews tab."""


def parse_review_rows(
    raw_items: list[dict[str, Any]], *, limit: int | None = None
) -> list[MapsReview]:
    if limit is not None:
        raw_items = raw_items[:limit]
    reviews: list[MapsReview] = []
    for item in raw_items:
        username = normalize_text(item.get("username", ""))
        text = normalize_text(item.get("text", ""))
        date_text = normalize_text(item.get("date_text", ""))
        reviews.append(
            MapsReview(
                external_id=normalize_text(item.get("external_id", "")),
                stars=int(item.get("stars", 0)),
                username=username,
                text=text,
                date_text=date_text,
                date=parse_relative_date(date_text),
            )
        )
    return reviews


def read_visible_reviews(page: Any, *, limit: int | None = None) -> list[MapsReview]:
    return parse_review_rows(evaluate_json(page, EXTRACT_REVIEWS_JS), limit=limit)


def scrape_reviews_on_page(
    page: Any,
    maps_url: str,
    *,
    max_reviews: int | None = None,
    known_ids: Collection[str] = (),
) -> list[MapsReview]:
    """Scrape reviews newest first. Scrolling stops at the first review whose
    resolved external id is in `known_ids`, since everything older is already stored."""
    if max_reviews is not None and max_reviews <= 0:
        return []

    navigate_to_place(page, maps_url)
    if is_limited_maps_view(page):
        raise GoogleLimitedViewError("Google Maps is showing a limited view — reviews unavailable")
    if not click_reviews_tab(page):
        raise GoogleReviewsUnavailableError("Could not open the Google Maps reviews tab")

    set_reviews_sort(page, label="Newest")

    with contextlib.suppress(Exception):
        page.wait_for_selector("div[data-review-id], div.jftiEf", timeout=12000)
    page.wait_for_timeout(1500)

    seen: dict[str, MapsReview] = {}
    reached_known = False
    idle_rounds = 0
    max_scrolls = 80 if max_reviews is None else max(10, min(80, max_reviews // 2 + 8))
    for _ in range(1, max_scrolls + 1):
        for review in read_visible_reviews(page, limit=max_reviews):
            external_id = review.resolved_external_id()
            seen[external_id] = MapsReview(
                external_id=external_id,
                stars=review.stars,
                username=review.username,
                text=review.text,
                date_text=review.date_text,
                date=review.date,
            )
            reached_known = reached_known or external_id in known_ids
        if reached_known or (max_reviews is not None and len(seen) >= max_reviews):
            break
        before = len(seen)
        if not scroll_reviews_pane(page):
            idle_rounds += 1
        else:
            idle_rounds = 0
        if len(seen) == before:
            idle_rounds += 1
        if idle_rounds >= 6:
            break
        time.sleep(0.5)

    if not seen:
        raise GoogleReviewsUnavailableError("No review cards found on the page")
    reviews = list(seen.values())
    return reviews if max_reviews is None else reviews[:max_reviews]


def scrape_reviews(
    maps_url: str,
    *,
    max_reviews: int | None = None,
    known_ids: Collection[str] = (),
    page: Any = None,
    context: Any = None,
    headless: bool = True,
) -> list[MapsReview]:
    """Scrape reviews off a Google Maps place URL.

    Pass an existing `page` or browser `context` to reuse a running browser;
    otherwise a throwaway Playwright browser is launched for the call.
    """
    if page is not None:
        return scrape_reviews_on_page(page, maps_url, max_reviews=max_reviews, known_ids=known_ids)
    if context is not None:
        owned_page = open_page(context)
        try:
            return scrape_reviews_on_page(
                owned_page, maps_url, max_reviews=max_reviews, known_ids=known_ids
            )
        finally:
            owned_page.close()

    from gmbscraper._scraper import google_maps_browser

    with google_maps_browser(headless=headless) as scraper:
        return scraper.scrape_reviews(maps_url, max_reviews=max_reviews, known_ids=known_ids)
