import json
import random
from functools import lru_cache
from pathlib import Path

from app.config import get_settings

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


class ToolExecutionError(RuntimeError):
    """Fallo (simulado o real) del servicio externo detrás de una tool."""


def maybe_fail(tool_name: str) -> None:
    """Inyección de fallos controlada por MOCK_FAILURE_RATE para demostrar los reintentos."""
    rate = get_settings().mock_failure_rate
    if rate > 0 and random.random() < rate:
        raise ToolExecutionError(f"{tool_name}: servicio no disponible (fallo simulado)")


@lru_cache
def load_json(name: str) -> dict:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))
