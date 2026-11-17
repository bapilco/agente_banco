"""Trazabilidad: qué agente se llamó, en qué intento, con qué herramientas y cuánto tardó."""

from datetime import datetime, timezone
from typing import Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def trace_entry(
    *,
    agent: str,
    attempt: int,
    status: str,
    started_at: str,
    duration_ms: float,
    tools_called: Optional[list[str]] = None,
    error: Optional[str] = None,
    notes: Optional[list[str]] = None,
) -> dict:
    entry = {
        "agent": agent,
        "attempt": attempt,
        "status": status,
        "started_at": started_at,
        "duration_ms": round(duration_ms, 2),
        "tools_called": tools_called or [],
    }
    if error:
        entry["error"] = error
    if notes:
        entry["notes"] = notes
    return entry
