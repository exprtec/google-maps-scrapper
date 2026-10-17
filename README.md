# gmbscraper

A typed, importable Playwright scraper for Google Maps / Google Business Profile data:
place search, place details, identity-based matching, review scraping, and
parallel fan-out helpers.

- Search Google Maps and scrape place details (name, category, address, phone,
  website, rating, review count) without the official (paid, rate-limited)
  Places API.
- Adaptive quadrant search that recursively splits the map viewport to pull
  results beyond Google's ~120-per-query cap.
- Confidence-tiered identity matching (`phone_and_domain_match` >
  `phone_match` > `domain_match` > `exact_name_match`) for matching a known
  business/outlet against scraped candidates.
- Review scraping with owner-response filtering, "see more" text expansion,
  and multilingual review-tab detection.
- Thread-based fan-out helpers (`chunk_items`, `run_chunked`) for running
  multiple browser workers over a batch of items.

> **Status:** pre-1.0 (`0.x`). Extracted from duplicated scraping code across
> several internal projects; the API may still move before `1.0.0`.

Using this from another project (agent or human)? Read [`skills/SKILL.md`](skills/SKILL.md) first — it covers the API surface, matching semantics, parallel fan-out, and how to add this as a dependency before PyPI publication.

## Install

Not yet published to PyPI. Add it as a `uv` path dependency — see [`skills/SKILL.md`](skills/SKILL.md#installing-in-a-consuming-project) for the exact `pyproject.toml` snippet — then:

```bash
uv run playwright install --with-deps chromium
```

## Quickstart

```python
from gmbscraper import BusinessIdentity, OutletIdentity, google_maps_browser

with google_maps_browser() as maps:
    # Search + adaptive pagination
    links = maps.search_places_adaptive("plumbers", latitude=-33.87, longitude=151.21)

    # Scrape a single place page
    place = maps.scrape_place(links[0].maps_url, fallback_name=links[0].fallback_name)
    print(place.name, place.rating, place.review_count)

    # Find the Google Business Profile for a known business
    match = maps.search_and_match(
        OutletIdentity(name="Acme Plumbing", phone="0400 000 000", address="1 Main St, Sydney"),
        BusinessIdentity(name="Acme Plumbing Pty Ltd", website="acmeplumbing.com.au"),
    )
    if match:
        print(match.match_reason, match.place_id)

    # Scrape reviews; on a re-sync, pass the ids you already store to stop
    # scrolling at the first known review
    reviews = maps.scrape_reviews(place.maps_url, max_reviews=50)
    newer = maps.scrape_reviews(place.maps_url, known_ids={r.external_id for r in reviews})
```

## Design notes

- Every network-facing function swallows and skips broken selectors rather
  than raising — a `PlaceProfile` is returned with whatever fields could be
  read, since Google's DOM/markup changes without notice and partial data is
  usually more useful than a hard failure. `scrape_reviews` is the exception:
  it raises `GoogleReviewsUnavailableError` when Google serves a page with no
  reviews UI at all (throttled/limited view, or the reviews tab never opens),
  since a caller needs to distinguish "zero reviews" from "couldn't scrape."
  Its `GoogleLimitedViewError` subclass marks Google's signed-out limited
  view, which signals throttling rather than a problem with one place.
- Each place opens in a single page load, and each browser launch gets a
  random desktop Chrome user agent unless you pass `user_agent=`.
- There's no retry/backoff or proxy rotation built in. This is a DOM scraper,
  not a hosted anti-block service — for scraping at a scale where blocking is
  routine, a paid API (Outscraper, SerpApi, etc.) will be cheaper than
  building that infrastructure yourself.

## Development

```bash
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

See [`skills/references/development.md`](skills/references/development.md) for what is and isn't covered by the test suite.

## License

MIT
