import unicodedata

from app.tools._common import load_json, maybe_fail


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " ".join(text.lower().split())


def _matches(entries: list[dict], name: str, document_id: str) -> list[dict]:
    norm_name = _normalize(name)
    found = []
    for entry in entries:
        if entry["document_id"] == document_id:
            found.append({**entry, "match_type": "document_id"})
        elif _normalize(entry["name"]) == norm_name:
            found.append({**entry, "match_type": "name"})
    return found


def check_risk_lists(name: str, document_id: str) -> dict:
    """Tool 2 (mock): consulta listas de riesgo (sanciones, PEP, etc.)."""
    maybe_fail("check_risk_lists")
    lists = load_json("risk_lists.json")

    high = _matches(lists["high_risk"], name, document_id)
    if high:
        return {"risk_level": "high", "matches": high}

    watch = _matches(lists["watch_list"], name, document_id)
    if watch:
        return {"risk_level": "medium", "matches": watch}

    return {"risk_level": "low", "matches": []}
