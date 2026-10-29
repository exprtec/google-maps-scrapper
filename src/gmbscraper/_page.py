from __future__ import annotations

import contextlib
import re
import time
from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from gmbscraper.parsing import (
    normalize_text,
    parse_review_count_label,
)

LIMITED_VIEW_PHRASES = (
    "limited view",
    "vue limitée",
    "eingeschränkte ansicht",
    "vista limitada",
    "vista limitata",
)

# Map tiles, photos and fonts are most of Chromium's CPU; scraping only reads text.
BLOCKED_URLS = (
    "*/maps/vt*",
    "*/vt/icon*",
    "*fonts.gstatic.com/*",
    "*googleusercontent.com/*",
    "*streetviewpixels-pa.googleapis.com/*",
    "*maps.gstatic.com/*",
    "*/images/branding/*",
)

REVIEW_TAB_WORDS = frozenset(
    {
        "reviews",
        "review",
        "ratings",
        "rating",
        "avis",
        "bewertungen",
        "reseñas",
        "recensioni",
        "avaliações",
        "отзывы",
        "レビュー",
        "리뷰",
        "评论",
        "評論",
        "ביקורות",
    }
)

NON_REVIEW_TAB_WORDS = frozenset(
    {
        "menu",
        "overview",
        "about",
        "photos",
        "updates",
        "products",
        "services",
        "directions",
        "posts",
        "aperçu",
        "à propos",
        "übersicht",
        "speisekarte",
        "menú",
        "resumen",
        "acerca",
    }
)

REVIEWS_TAB_SELECTORS = (
    '[role="tab"][aria-label*="review" i]',
    '[role="tab"][aria-label*="avis" i]',
    '[role="tab"][aria-label*="bewertung" i]',
    '[role="tab"][aria-label*="reseña" i]',
    '[role="tab"][data-tab-index]',
    'button[role="tab"]',
    'div[role="tab"]',
)


def open_page(context: Any) -> Any:
    """Open a Chromium page that skips downloading map tiles, photos and fonts."""
    page = context.new_page()
    session = context.new_cdp_session(page)
    session.send("Network.enable")
    session.send("Network.setBlockedURLs", {"urls": list(BLOCKED_URLS)})
    return page


def wait_for_content(page: Any, selectors: tuple[str, ...], *, max_wait_ms: int) -> None:
    """Wait until each selector renders, sharing one `max_wait_ms` budget across them all."""
    deadline = time.monotonic() + max_wait_ms / 1000
    for selector in selectors:
        remaining_ms = (deadline - time.monotonic()) * 1000
        if remaining_ms <= 0:
            return
        try:
            page.wait_for_selector(selector, timeout=remaining_ms)
        except PlaywrightTimeoutError:
            return


def accept_consent(page: Any) -> None:
    for selector in (
        "button:has-text('Accept all')",
        "button:has-text('I agree')",
        "button[aria-label='Accept all']",
        'button[aria-label*="Accept" i]',
        'button[jsname="hZCF7e"]',
    ):
        try:
            button = page.locator(selector).first
            if button.count() > 0:
                button.click(timeout=1500)
                page.wait_for_timeout(1000)
                return
        except Exception:
            continue


def first_text(page: Any, selectors: tuple[str, ...]) -> str:
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() > 0:
                value = normalize_text(locator.inner_text(timeout=2000))
                if value:
                    return value
        except Exception:
            continue
    return ""


def first_attr(page: Any, selectors: tuple[str, ...], attr: str) -> str:
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() > 0:
                value = normalize_text(locator.get_attribute(attr, timeout=2000))
                if value:
                    return value
        except Exception:
            continue
    return ""


def read_aggregate_review_count(page: Any) -> int | None:
    try:
        values = page.evaluate(
            """() => {
                const heading = document.querySelector('h1.DUwDvf, h1');
                const root = heading?.closest('div[role="main"]')
                    || document.querySelector('div[role="main"]');
                if (!root) return [];
                return Array.from(root.querySelectorAll('[aria-label], span, button'))
                    .flatMap((el) => [
                        el.getAttribute('aria-label') || '',
                        (el.textContent || '').trim(),
                    ])
                    .filter(Boolean)
                    .slice(0, 200);
            }"""
        )
    except Exception:
        values = []
    for value in values:
        count = parse_review_count_label(value)
        if count is not None:
            return count
    return None


def is_limited_maps_view(page: Any) -> bool:
    """Detect Google's stripped-down signed-out view — a sign of soft-blocking or throttling."""
    try:
        body_text = normalize_text(page.locator("body").inner_text(timeout=2000)).lower()
    except Exception:
        return False
    if any(phrase in body_text for phrase in LIMITED_VIEW_PHRASES):
        return True
    try:
        sign_in_visible = (
            page.locator('a[data-action="sign in"], a[href*="ServiceLogin"]').count() > 0
        )
        tab_present = page.locator('[role="tab"]').count() > 0
        return sign_in_visible and not tab_present
    except Exception:
        return False


def _text_contains_any(text: str, words: frozenset[str]) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in words)


def score_reviews_tab(aria_label: str, tab_text: str, tab_index: str) -> float:
    score = 0.0
    if _text_contains_any(aria_label, REVIEW_TAB_WORDS):
        score += 1.5
    if _text_contains_any(tab_text, REVIEW_TAB_WORDS):
        score += 1.0
    if _text_contains_any(aria_label, NON_REVIEW_TAB_WORDS):
        score -= 1.5
    if _text_contains_any(tab_text, NON_REVIEW_TAB_WORDS):
        score -= 1.0
    if tab_index in ("1", "reviews") and score > 0:
        score += 0.25
    return score


def navigate_to_place(page: Any, maps_url: str) -> None:
    """Open a place URL in one page load. Every extra load costs request budget
    that Google throttles per session, so there is no warm-up or search detour."""
    page.goto(maps_url, wait_until="domcontentloaded", timeout=45000)
    accept_consent(page)
    wait_for_content(page, ('[role="tab"]', "h1"), max_wait_ms=8000)


def verify_reviews_panel(page: Any) -> bool:
    if page.locator("div[data-review-id], div.jftiEf").count() > 0:
        return True
    if "/reviews" in (page.url or "").lower():
        return True
    return page.locator('button[aria-label*="Sort" i]').count() > 0


def click_reviews_tab(page: Any) -> bool:
    for selector in REVIEWS_TAB_SELECTORS:
        try:
            tabs = page.locator(selector).all()
        except Exception:
            continue
        for tab in tabs[:12]:
            try:
                aria_label = tab.get_attribute("aria-label") or ""
                tab_text = normalize_text(tab.inner_text(timeout=500))
                tab_index = tab.get_attribute("data-tab-index") or ""
                score = score_reviews_tab(aria_label, tab_text, tab_index)
                if score < 1.5:
                    continue
                tab.scroll_into_view_if_needed(timeout=2000)
                page.wait_for_timeout(400)
                tab.click(timeout=3000)
                page.wait_for_timeout(2000)
                if verify_reviews_panel(page):
                    return True
            except Exception:
                continue

    current_url = page.url or ""
    if "/place/" in current_url and "/reviews" not in current_url:
        reviews_url = re.sub(r"(/place/[^/]+)(?:/|$)", r"\1/reviews", current_url, count=1)
        if reviews_url != current_url:
            try:
                page.goto(reviews_url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(2500)
                if verify_reviews_panel(page):
                    return True
            except Exception:
                pass
    return verify_reviews_panel(page)


def set_reviews_sort(page: Any, *, label: str = "Newest") -> bool:
    try:
        sort_btn = page.locator('button[aria-label*="Sort" i]').first
        if sort_btn.count() == 0:
            return False
        sort_btn.scroll_into_view_if_needed(timeout=3000)
        page.wait_for_timeout(400)
        sort_btn.click(timeout=5000)
        page.wait_for_timeout(1500)
        option = page.locator(
            f'[role="menuitemradio"]:has-text("{label}"), [role="menuitem"]:has-text("{label}")'
        ).first
        if option.count() == 0:
            return False
        option.click(timeout=5000)
        page.wait_for_timeout(2500)
        return True
    except Exception:
        return False


def resolve_maps_place_url(page: Any, maps_url: str) -> str:
    current_url = page.url or maps_url
    if "/maps/place/" in current_url:
        return current_url
    if "/maps/search/" not in current_url:
        return current_url
    try:
        title = page.locator("h1.DUwDvf, h1").first
        if title.count() > 0:
            title.click(timeout=3000)
            page.wait_for_timeout(2000)
            page.wait_for_url("**/maps/place/**", timeout=10000)
    except Exception:
        pass
    return page.url or current_url


def scroll_reviews_pane(page: Any, *, wait_ms: int = 900) -> bool:
    scrolled = page.evaluate(
        """() => {
            const main = document.querySelector('div[role="main"]') || document.body;
            const cards = main.querySelectorAll('div[data-review-id], div.jftiEf');
            let scroller = null;
            if (cards.length > 0) {
                let node = cards[cards.length - 1].parentElement;
                while (node && node !== document.body) {
                    if (node.scrollHeight > node.clientHeight + 20) {
                        scroller = node;
                        break;
                    }
                    node = node.parentElement;
                }
            }
            if (!scroller) {
                scroller = main.querySelector('div.m6QErb.DxyBCb.kA9KIf.dS8AEf')
                    || main.querySelector('div.m6QErb[tabindex="-1"]')
                    || main.querySelector('div[role="feed"]')
                    || main.querySelector('div.section-scrollbox')
                    || main.querySelector('div.m6QErb');
            }
            if (!scroller) return false;
            const beforeTop = scroller.scrollTop;
            const beforeHeight = scroller.scrollHeight;
            scroller.scrollTop = scroller.scrollHeight;
            window.scrollTo(0, document.body.scrollHeight);
            const moved = scroller.scrollTop > beforeTop;
            const grew = scroller.scrollHeight > beforeHeight;
            return moved || grew;
        }"""
    )
    if not scrolled:
        try:
            panel = page.locator("div[role='main']").first
            if panel.count() > 0:
                panel.hover(timeout=1000)
                page.mouse.wheel(0, 3000)
                scrolled = True
        except Exception:
            pass
    if scrolled:
        page.wait_for_timeout(wait_ms)
    return bool(scrolled)


def scroll_search_results(page: Any) -> dict[str, bool]:
    state: Any = {"scrolled": False, "at_end": False}
    with contextlib.suppress(Exception):
        state = page.evaluate(
            """() => {
                const feed = document.querySelector('div[role="feed"]');
                if (!feed) return {scrolled: false, at_end: false};
                let scroller = feed;
                let current = feed;
                while (current && current !== document.body) {
                    if (current.scrollHeight > current.clientHeight + 20) {
                        scroller = current;
                        break;
                    }
                    current = current.parentElement;
                }
                const endPhrases = [
                    "you've reached the end of the list",
                    "you have reached the end of the list",
                    "end of the list"
                ];
                const beforeTop = scroller.scrollTop;
                const beforeHeight = scroller.scrollHeight;
                const cards = Array.from(feed.querySelectorAll('div[role="article"]'));
                const lastCard = cards[cards.length - 1];
                if (lastCard) {
                    lastCard.scrollIntoView({block: "end"});
                }
                scroller.scrollBy({
                    top: Math.max(scroller.clientHeight * 1.5, 900),
                    behavior: "auto"
                });
                const text = (feed.innerText || "").toLowerCase();
                const atEndByText = endPhrases.some((phrase) => text.includes(phrase));
                const moved = scroller.scrollTop > beforeTop
                    || scroller.scrollHeight > beforeHeight;
                return {
                    scrolled: moved,
                    at_end: atEndByText
                };
            }"""
        )
    with contextlib.suppress(Exception):
        feed = page.locator('div[role="feed"]').first
        if feed.count() > 0:
            feed.hover(timeout=1000)
            page.mouse.wheel(0, 1800)
    page.wait_for_timeout(900)
    if not isinstance(state, dict):
        return {"scrolled": False, "at_end": False}
    return {
        "scrolled": bool(state.get("scrolled")),
        "at_end": bool(state.get("at_end")),
    }


def evaluate_json(page: Any, script: str) -> list[dict[str, Any]]:
    try:
        result = page.evaluate(script)
    except Exception:
        return []
    if not isinstance(result, list):
        return []
    return [item for item in result if isinstance(item, dict)]
