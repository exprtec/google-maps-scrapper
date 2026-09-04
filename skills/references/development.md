# Development

Working on `gmbscraper` itself (not just consuming it).

## Setup

```bash
uv sync
uv run playwright install --with-deps chromium  # only needed to exercise real scraping, not for the unit tests below
```

## Validation

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

The test suite covers `parsing.py`, `_matching.py`, and `_parallel.py` only — everything that touches a real `Page`/`BrowserContext` (`_page.py`, `_places.py`, `_adaptive_search.py`, `_reviews.py`, `_scraper.py`) has no automated coverage and is verified by running it against live Google Maps. Keep new logic in the parsing/matching/parallel modules pure and unit-testable where possible; push anything that must touch a `page` object into the browser-facing modules, which stay manually verified.

## Versioning

`src/gmbscraper/_version.py` is the single source of truth (`__version__ = "x.y.z"`), read by both the package's own `__init__.py` and `pyproject.toml`'s `[tool.hatch.version]`. Bump it there — nowhere else.

## Not Yet Published

There's no PyPI release and no publish workflow yet. Consuming projects use a `tool.uv.sources` path dependency (see the main [SKILL.md](../SKILL.md#installing-in-a-consuming-project)). If this gets published later, mirror `instantly-python-sdk`'s pattern (`instantlyai` on PyPI, `scripts/release.sh`, version-pinned dependency in consumers) rather than inventing a new one.
