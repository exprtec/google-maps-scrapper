---
name: gmbscraper
description: Google Maps / Google Business Profile scraping via the `gmbscraper` package. Use when writing or reviewing code that searches Google Maps for places, scrapes a place's details, matches a known business/outlet against scraped candidates, or scrapes Google Maps reviews — in this repo or any project that depends on `gmbscraper` (e.g. reviewMonster, automation) — and when modifying gmbscraper's own scraper, matching, parsing, or review internals.
---

# gmbscraper

Playwright-based scraper for Google Maps / Google Business Profile data. No official API key, no Places API quota — it drives a real (stealth-configured) Chromium browser against maps.google.com.

## Quick Reference

* Not on PyPI yet. Add it as a path (or git) dependency; see [Installing In A Consuming Project](#installing-in-a-consuming-project) below.
* Everything flows through one object: `with google_maps_browser() as scraper:` yields a `GoogleMapsScraper`. Open one per thread if you fan out — see [Parallel Fan-out](references/parallel-fanout.md).
* Search: `scraper.search_places_adaptive(query, latitude=.., longitude=..)` → `list[MapsSearchLink]`. Handles Google's ~120-results-per-query cap by splitting the map viewport automatically; safe to use even when you don't expect a saturated result set. Pass the location's coordinates and zoom (from `scraper.locate("Amberley, NZ")` → `MapsView`, or zoom 12 by default): splitting then stays within that area instead of the (often region-wide) view Google picked for the seed query.
* Place detail: `scraper.scrape_place(url, fallback_name=.., rank=..)` → `PlaceProfile`. Never raises — a selector miss just leaves that field blank, so check for empty strings, not exceptions.
* Identity matching: `scraper.search_and_match(outlet, business)` → `PlaceProfile | None`, scored by phone/domain/name confidence. See [Matching](references/matching.md) before hand-rolling any similarity check.
* Reviews: `scraper.scrape_reviews(maps_url)` → `list[MapsReview]`. Unlimited by default (`max_reviews=None`) — this is the one call that raises: `GoogleReviewsUnavailableError` when there's no reviews UI to open at all (blocked/limited view, or truly zero reviews).
* Pass `locale=` to `google_maps_browser` matching the business's country (`"en-AU"`, `"en-NZ"`, ...) — it changes the address/phone formatting Google renders, which downstream parsing assumes.
* Long-running jobs should pass `stall_timeout=` (seconds) to `google_maps_browser`: a call that stops making progress gets its browser killed and raises `BrowserStalledError`, and the next call relaunches the browser.
* Pages skip map tiles, photos and fonts (and the launched browser skips images), which halves Chromium's CPU. Don't scrape anything that needs them rendered.
* No retry/backoff/proxy rotation is built in. This is a DOM scraper, not an anti-block service — see [Limits](#limits).
* Package development (tests, lint, versioning): see [Development](references/development.md).

## Search, Then Scrape

```python
from gmbscraper import google_maps_browser

with google_maps_browser(locale="en-AU") as scraper:
    links = scraper.search_places_adaptive("plumbers", latitude=-33.87, longitude=151.21)
    for link in links:
        place = scraper.scrape_place(link.maps_url, fallback_name=link.fallback_name)
        print(place.name, place.rating, place.review_count)
```

`MapsSearchLink` has `maps_url`, `fallback_name`, and `search_rank` (`None` for links found via viewport-splitting rather than the original query). Dedup on `maps_url` — adaptive search can revisit the same place across overlapping quadrants.

## Matching A Known Business

Use this instead of writing your own name-similarity check — a plain fuzzy-name match produces false positives across chains and franchises. `search_and_match` needs at least one strong identity signal (phone, website, or an exact name) to return anything:

```python
from gmbscraper import BusinessIdentity, OutletIdentity, google_maps_browser

with google_maps_browser() as scraper:
    place = scraper.search_and_match(
        OutletIdentity(name="Acme Plumbing", phone="0400 000 000", address="1 Main St, Sydney"),
        BusinessIdentity(name="Acme Plumbing Pty Ltd", website="acmeplumbing.com.au"),
    )
    if place is not None:
        print(place.match_reason)  # e.g. "phone_and_domain_match"
```

`place is None` means no candidate cleared the confidence bar — treat it as "no match," not as an error. Full tier breakdown and the standalone matching functions (for scoring your own candidate lists) are in [Matching](references/matching.md).

## Scraping Reviews

```python
from gmbscraper import GoogleReviewsUnavailableError, google_maps_browser

with google_maps_browser() as scraper:
    try:
        reviews = scraper.scrape_reviews(place.maps_url)
    except GoogleReviewsUnavailableError:
        reviews = []
```

Each `MapsReview` has `stars`, `username`, `text`, `date_text` (raw), `date` (resolved ISO string, `""` if unparseable), and `external_id` — call `.resolved_external_id()` instead of reading `.external_id` directly when you need a stable dedup key, since Google omits the id on some cards and the method falls back to a content hash.

Pass `max_reviews=N` to stop early once you have enough; omitting it scrapes everything reachable (bounded by an idle-scroll cutoff, not a hard count).

## Installing In A Consuming Project

Not published to PyPI yet, so add it as a `uv` path source rather than a version pin. From a project two directories under `Documents/Work/<project>/<subdir>` (matches both `automation/worker` and `reviewMonster/backend`):

```toml
# pyproject.toml
[project]
dependencies = ["gmbscraper"]

[tool.uv.sources]
gmbscraper = { path = "../../../open-source/google-maps-python" }
```

Then `uv sync`. Adjust the relative path if your project sits at a different depth. `automation/worker/pyproject.toml` has a working example to copy from.

If your project also needs Playwright's browser binary (it almost certainly does, since gmbscraper only declares the `playwright` Python package): `uv run playwright install --with-deps chromium`. Check whether the target repo's Dockerfile already runs this for its own Playwright usage before adding a second install step.

## Limits

* No retry/backoff and no proxy rotation. Google will eventually throttle a browser that scrapes hard enough from one IP; `is_limited_maps_view`-style detection exists only inside review scraping (surfaced as `GoogleReviewsUnavailableError`), not on the search/place-detail path — a throttled search silently returns thin/empty results rather than raising. If you need resilience against sustained blocking at scale, that's a paid API's job (Outscraper, SerpApi), not this package's.
* Name/phone/domain normalization (`normalize_name`, `normalize_phone`, `normalize_domain`) is AU/NZ-tuned: it strips `pty`/`ltd`, AU/NZ multi-part TLD suffixes (`com.au`, `co.nz`, ...), and converts phone numbers to a local-format suffix assuming AU-style `+61` numbers. Matching businesses outside AU/NZ will work but with weaker name normalization.
* `match_place` mutates the `PlaceProfile` it's given (sets `.match_reason`) rather than returning a copy — don't reuse the same `PlaceProfile` instance across multiple `match_place` calls against different identities, or the reason from an earlier failed match can leak into a later check.
