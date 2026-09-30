"""Streaming access to the trusted, build-time offline model bundle."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any, Iterator

BUNDLE = Path(__file__).parent / "data/track-models.bundle.json.gz"


def iter_models(path: Path = BUNDLE) -> Iterator[dict[str, Any]]:
    """Decode one model at a time rather than retaining the whole catalogue's JSON tree."""
    decoder = json.JSONDecoder()
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        buffer = ""
        marker = '"models":'
        while marker not in buffer:
            chunk = stream.read(65536)
            if not chunk:
                raise ValueError("Missing model bundle section")
            buffer = buffer[-len(marker) :] + chunk
        buffer = buffer.split(marker, 1)[1].lstrip()
        if not buffer.startswith("{"):
            raise ValueError("Invalid model bundle")
        buffer = buffer[1:]
        while True:
            buffer = buffer.lstrip(" \n\r\t,")
            if buffer.startswith("}"):
                return
            try:
                key, end = decoder.raw_decode(buffer)
                tail = buffer[end:].lstrip()
                if not tail.startswith(":"):
                    raise json.JSONDecodeError("Incomplete member", buffer, end)
                tail = tail[1:].lstrip()
                model, consumed = decoder.raw_decode(tail)
            except json.JSONDecodeError:
                chunk = stream.read(65536)
                if not chunk:
                    raise ValueError("Truncated model bundle") from None
                buffer += chunk
                if len(buffer) > 16 * 1024 * 1024:
                    raise ValueError("Model exceeds bundle size limit")
                continue
            if model.get("layout_id") != key:
                raise ValueError("Bundle identity mismatch")
            buffer = tail[consumed:]
            yield model


def get_model(layout_id: str) -> dict[str, Any] | None:
    """Read an individual bundled model without introducing an unbounded document cache."""
    return next((model for model in iter_models() if model["layout_id"] == layout_id), None)
