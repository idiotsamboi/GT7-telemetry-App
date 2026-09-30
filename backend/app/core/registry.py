"""One registry pattern for channels, commands, capabilities, modules, ... (docs/architecture)."""
from typing import Callable, Generic, Iterator, TypeVar

T = TypeVar('T')


class DuplicateRegistration(ValueError):
    pass


class Registry(Generic[T]):
    """id -> item. Duplicate ids fail at import time, so a bad registration cannot go unnoticed."""

    def __init__(self, name: str, key: Callable[[T], str] = lambda item: item.id,
                 public: Callable[[T], dict] | None = None):
        self.name = name
        self._key = key
        self._public = public
        self._items: dict[str, T] = {}

    def register(self, item: T) -> T:
        key = self._key(item)
        if key in self._items:
            raise DuplicateRegistration(f'{self.name}: duplicate id {key!r}')
        self._items[key] = item
        return item

    def get(self, key: str) -> T | None:
        return self._items.get(key)

    def require(self, key: str) -> T:
        try:
            return self._items[key]
        except KeyError:
            raise KeyError(f'{self.name}: unknown id {key!r}') from None

    def all(self) -> list[T]:
        return list(self._items.values())

    def ids(self) -> list[str]:
        return list(self._items)

    def __contains__(self, key: str) -> bool:
        return key in self._items

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[T]:
        return iter(self._items.values())

    def to_public(self) -> list[dict]:
        """JSON-safe description (never callables); used by /api/* listings and contract generation."""
        if self._public:
            return [self._public(i) for i in self._items.values()]
        from dataclasses import asdict, is_dataclass
        out = []
        for item in self._items.values():
            if is_dataclass(item):
                out.append({k: v for k, v in asdict(item).items() if not callable(v)})
            else:
                out.append(dict(item))
        return out
