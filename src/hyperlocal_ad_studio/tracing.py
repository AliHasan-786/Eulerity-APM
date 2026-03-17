from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import re

from .models import TraceEvent


def _sanitize(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", value.strip())
    return cleaned.strip("-") or "unknown"


def trace_filename(request_id: str, zip_code: str) -> str:
    return f"{_sanitize(request_id)}-{_sanitize(zip_code)}.json"


def load_trace(trace_dir: Path, request_id: str, zip_code: str) -> list[dict[str, object]]:
    trace_path = trace_dir / trace_filename(request_id=request_id, zip_code=zip_code)
    with trace_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class TraceRecorder:
    def __init__(self, trace_dir: Path, request_id: str, zip_code: str) -> None:
        self._trace_dir = trace_dir
        self._request_id = request_id
        self._zip_code = zip_code
        self._events: list[TraceEvent] = []

    @property
    def trace_id(self) -> str:
        return f"{self._request_id}:{self._zip_code}"

    def record(self, step: str, payload: dict[str, object]) -> None:
        self._events.append(TraceEvent.create(step=step, payload=payload))

    def events_as_list(self) -> list[dict[str, object]]:
        return [asdict(event) for event in self._events]

    def flush(self) -> str:
        self._trace_dir.mkdir(parents=True, exist_ok=True)
        trace_path = self._trace_dir / trace_filename(
            request_id=self._request_id,
            zip_code=self._zip_code,
        )
        with trace_path.open("w", encoding="utf-8") as handle:
            json.dump([asdict(event) for event in self._events], handle, indent=2)
        return str(trace_path)
