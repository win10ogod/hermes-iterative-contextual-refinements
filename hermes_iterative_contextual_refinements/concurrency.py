"""Stage-level concurrency helpers.

ICR's browser implementation uses Promise.all for same-stage agent work.  The
Hermes plugin preserves that contract with thread pools sized to the stage.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Iterable, TypeVar

T = TypeVar("T")
R = TypeVar("R")


def run_parallel(items: Iterable[T], fn: Callable[[T], R]) -> list[R]:
    values = list(items)
    if not values:
        return []
    if len(values) == 1:
        return [fn(values[0])]
    results: list[R | None] = [None] * len(values)
    with ThreadPoolExecutor(max_workers=len(values), thread_name_prefix="icr-stage") as pool:
        futures = {pool.submit(fn, item): index for index, item in enumerate(values)}
        for future in as_completed(futures):
            results[futures[future]] = future.result()
    return [result for result in results if result is not None]
