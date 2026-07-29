"""Append-only event log. The frontend's only interface to the pipeline.

There is no API between the two processes. The pipeline appends JSON lines; the
UI polls the file. No server to crash mid-demo, no ports, no CORS, no async
lifecycle bug at 18:40.

It also gives replay mode for free: the UI reads an event stream, so a recorded
run replays through the identical code path. That is the demo fallback, and it
is better than a video because it IS the real interface.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from forecaster.schemas import Event, EventType


class EventLog:
    def __init__(self, path: Path | str = "out/events.ndjson") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("")
        self._seq = 0
        self._t0 = time.monotonic()

    def emit(self, type_: EventType, node: str | None = None, **payload) -> None:
        self._seq += 1
        event = Event(
            seq=self._seq,
            type=type_,
            node=node,
            ts_ms=int((time.monotonic() - self._t0) * 1000),
            payload=payload,
        )
        with self.path.open("a") as fh:
            fh.write(event.model_dump_json() + "\n")

    def node(self, name: str):
        return _Node(self, name)


class _Node:
    """Context manager so a stage cannot forget to report that it finished."""

    def __init__(self, log: EventLog, name: str) -> None:
        self.log, self.name = log, name

    def __enter__(self) -> _Node:
        self.log.emit(EventType.NODE_START, self.name)
        self._t = time.monotonic()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        ms = int((time.monotonic() - self._t) * 1000)
        if exc_type is None:
            self.log.emit(EventType.NODE_DONE, self.name, latency_ms=ms)
        else:
            # A failed node is shown greyed with its reason, not hidden.
            # Something will fail live; make failure look intentional.
            self.log.emit(
                EventType.NODE_FAILED, self.name, latency_ms=ms, error=str(exc)
            )
        return False


def read_events(path: Path | str) -> list[Event]:
    """Used by replay mode and by the golden-file tests."""
    return [
        Event(**json.loads(line))
        for line in Path(path).read_text().splitlines()
        if line.strip()
    ]
