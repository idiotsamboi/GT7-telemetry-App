"""Shared computed snapshots: N subscribers with the same view share one computation."""
import time
from collections import OrderedDict
from typing import Any, Callable, Hashable


class SnapshotCache:
    """Bounded, short-lived cache keyed by (view filter, delay, revision, frame).

    The key must contain everything the value depends on (see GroupService.public_state); the
    cache only adds a max age (default 200 ms, one tick) and a size bound. `clear()` is called when
    the group document changes, so a revision bump never serves stale data.
    """

    def __init__(self, *, max_entries: int = 64, max_age: float = 0.2, clock: Callable[[], float] = time.monotonic):
        self.max_entries, self.max_age, self.clock = max_entries, max_age, clock
        self._items: OrderedDict[Hashable, tuple[float, Any]] = OrderedDict()
        self.computations = 0
        self.hits = 0

    def get(self, key: Hashable, compute: Callable[[], Any]) -> Any:
        now = self.clock()
        hit = self._items.get(key)
        if hit is not None and now - hit[0] <= self.max_age:
            self.hits += 1
            self._items.move_to_end(key)
            return hit[1]
        value = compute()
        self.computations += 1
        self._items[key] = (now, value)
        self._items.move_to_end(key)
        while len(self._items) > self.max_entries:
            self._items.popitem(last=False)
        return value

    def clear(self) -> None:
        self._items.clear()

    def __len__(self) -> int:
        return len(self._items)
