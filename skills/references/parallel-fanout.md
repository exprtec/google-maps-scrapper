# Parallel Fan-out

`chunk_items` and `run_chunked` split a batch of work across threads, each running its own browser. Reach for these when you have more than a handful of places/leads/reviews to process in one job and want to run several browsers concurrently instead of one after another.

## One Browser Per Thread — Not One Shared Browser

Playwright's *sync* API (what `google_maps_browser` uses) is not thread-safe. Each worker thread must open its own `google_maps_browser()` context — never pass a single `GoogleMapsScraper` into multiple threads. `run_chunked` hands each worker a *chunk of items*, not a shared scraper, specifically so each worker opens its own browser internally:

```python
from gmbscraper import google_maps_browser, run_chunked


def worker(chunk: list[MyItem], worker_id: int) -> MyStats:
    stats = MyStats()
    with google_maps_browser() as scraper:  # one browser per worker thread
        for item in chunk:
            ...  # scraper.scrape_place(...) / .search_and_match(...) / .scrape_reviews(...)
    return stats


final = run_chunked(items, workers=4, empty_stats=MyStats, worker=worker)
```

If `workers >= len(items)` (or `workers=1`), `run_chunked` runs inline on the calling thread without spawning an executor at all — safe to always pass a `--workers` CLI flag through even when it's 1.

## Additive Stats

`worker` must return an object satisfying the `AdditiveStats` protocol — just an `add(self, other) -> None` method that merges another instance's counts into itself. `run_chunked` calls `empty_stats()` once up front and `.add()` once per completed worker:

```python
from dataclasses import dataclass


@dataclass
class MyStats:
    matched: int = 0
    errors: int = 0

    def add(self, other: "MyStats") -> None:
        self.matched += other.matched
        self.errors += other.errors
```

## Chunking Only

If you want the even split without the threading (e.g. you're managing your own executor, or persisting through a DB session per chunk the way `automation`'s NDIS jobs do), call `chunk_items(items, workers)` directly — it returns `workers` lists (fewer if `len(items) < workers`), round-robin distributed so no chunk is more than one item larger than another.
