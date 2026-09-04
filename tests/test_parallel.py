from __future__ import annotations

from dataclasses import dataclass

from gmbscraper._parallel import chunk_items, run_chunked


def test_chunk_items_distributes_round_robin() -> None:
    chunks = chunk_items(list(range(7)), workers=3)
    assert sorted(item for chunk in chunks for item in chunk) == list(range(7))
    assert len(chunks) == 3


def test_chunk_items_caps_workers_to_item_count() -> None:
    chunks = chunk_items([1, 2], workers=10)
    assert len(chunks) == 2


@dataclass
class _Stats:
    total: int = 0

    def add(self, other: _Stats) -> None:
        self.total += other.total


def test_run_chunked_merges_worker_results() -> None:
    def worker(chunk: list[int], worker_id: int) -> _Stats:
        return _Stats(total=sum(chunk))

    result = run_chunked(list(range(10)), workers=4, empty_stats=_Stats, worker=worker)
    assert result.total == sum(range(10))


def test_run_chunked_single_worker_runs_inline() -> None:
    calls = []

    def worker(chunk: list[int], worker_id: int) -> _Stats:
        calls.append(worker_id)
        return _Stats(total=sum(chunk))

    result = run_chunked([1, 2, 3], workers=1, empty_stats=_Stats, worker=worker)
    assert result.total == 6
    assert calls == [1]
