from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Protocol


def chunk_items[T](items: list[T], workers: int) -> list[list[T]]:
    worker_count = max(1, min(workers, len(items)))
    chunks: list[list[T]] = [[] for _ in range(worker_count)]
    for index, item in enumerate(items):
        chunks[index % worker_count].append(item)
    return chunks


class AdditiveStats(Protocol):
    def add(self, other: AdditiveStats) -> None: ...


def run_chunked[T, S: AdditiveStats](
    items: list[T],
    workers: int,
    empty_stats: Callable[[], S],
    worker: Callable[[list[T], int], S],
) -> S:
    """Split `items` across `workers` threads, each running its own browser/session,
    and merge the additive stats objects they return.
    """
    chunks = chunk_items(items, workers)
    if len(chunks) == 1:
        return worker(chunks[0], 1)

    stats = empty_stats()
    with ThreadPoolExecutor(max_workers=len(chunks)) as executor:
        futures = [
            executor.submit(worker, chunk, index) for index, chunk in enumerate(chunks, start=1)
        ]
        for future in as_completed(futures):
            stats.add(future.result())
    return stats
