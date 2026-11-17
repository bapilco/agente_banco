"""Ejecución de un agente con reintentos (máx. N veces al mismo agente) y timeout por intento."""

import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from typing import Any, Optional

from app.config import get_settings
from app.orchestrator.tracing import trace_entry, utc_now_iso
from app.policies.onboarding_policy import FAILURE_ACTIONS


@dataclass
class RetryResult:
    output: Any = None  # AgentOutput si tuvo éxito
    trace: list[dict] = field(default_factory=list)
    error: Optional[dict] = None  # presente si fallaron todos los intentos


def _call_with_timeout(fn, arg, timeout: float):
    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(fn, arg)
    try:
        return future.result(timeout=timeout)
    except FutureTimeout as exc:
        raise TimeoutError(f"sin respuesta después de {timeout:.0f}s") from exc
    finally:
        pool.shutdown(wait=False)


def run_with_retry(agent, state: dict) -> RetryResult:
    settings = get_settings()
    max_attempts = max(1, settings.agent_max_retries)
    result = RetryResult()
    last_error = ""

    for attempt in range(1, max_attempts + 1):
        started_at = utc_now_iso()
        t0 = time.perf_counter()
        try:
            output = _call_with_timeout(agent.run, state, settings.agent_timeout_seconds)
        except Exception as exc:  # cualquier fallo del agente cuenta como intento fallido
            last_error = f"{type(exc).__name__}: {exc}"
            result.trace.append(trace_entry(
                agent=agent.name, attempt=attempt, status="failed", started_at=started_at,
                duration_ms=(time.perf_counter() - t0) * 1000,
                tools_called=getattr(exc, "tools_called", []), error=last_error,
            ))
            if attempt < max_attempts and settings.agent_retry_backoff_seconds > 0:
                time.sleep(settings.agent_retry_backoff_seconds * attempt)
            continue

        result.trace.append(trace_entry(
            agent=agent.name, attempt=attempt, status="success", started_at=started_at,
            duration_ms=(time.perf_counter() - t0) * 1000,
            tools_called=output.tools_called, notes=output.notes,
        ))
        result.output = output
        return result

    result.error = {
        "agent": agent.name,
        "attempts": max_attempts,
        "message": f"El agente {agent.name} falló {max_attempts} veces consecutivas. Último error: {last_error}",
        "suggested_action": FAILURE_ACTIONS.get(agent.name, "Revisión manual."),
    }
    return result
