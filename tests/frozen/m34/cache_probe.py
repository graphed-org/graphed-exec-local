"""Probes for M34 (importable by spawned workers): distinct processes + a cache-size reader."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Tagged:
    """A distinct picklable process per ``i`` (distinct content hash -> distinct cache entry)."""

    i: int

    def __call__(self, partition: object, resources: object) -> int:
        return self.i


def cache_size(partition: object, resources: object) -> int:
    from graphed_exec_local import executors  # noqa: PLC0415

    return len(executors._shared_objects)


def add(a: int, b: int) -> int:
    return a + b


def zero() -> int:
    return 0
