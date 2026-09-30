"""Small shared timing shapes. GT7 UDP carries no sector splits, so none are modelled (see SECTORS_NOTE)."""
from dataclasses import asdict, dataclass

SECTORS_NOTE = 'Sector splits are not transmitted by GT7 telemetry; none are inferred.'


@dataclass(frozen=True, slots=True)
class LapTime:
    lap: int
    duration_ms: int | None          # None when the lap has no trustworthy time
    source: str = 'unknown'          # e.g. 'game' | 'derived'
    comparable: bool = False

    @property
    def seconds(self) -> float | None:
        return None if self.duration_ms is None else self.duration_ms / 1000

    def to_public(self) -> dict:
        return asdict(self)

    @classmethod
    def from_lap(cls, lap: dict) -> 'LapTime':
        """From a stored lap payload ({number, duration_ms, timing_source, comparable, ...})."""
        return cls(lap=int(lap.get('number', 0)), duration_ms=lap.get('duration_ms') or None,
                   source=str(lap.get('timing_source') or 'unknown'), comparable=bool(lap.get('comparable')))


def best_lap(times: list[LapTime]) -> LapTime | None:
    valid = [t for t in times if t.comparable and t.duration_ms]
    return min(valid, key=lambda t: t.duration_ms) if valid else None
