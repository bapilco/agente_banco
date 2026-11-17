"""Aristas condicionales: el flujo es secuencial y se corta apenas no tiene sentido continuar."""

from app.config import get_settings


def after_identity(state: dict) -> str:
    identity = state.get("identity_result")
    if identity is None:  # el agente falló 3 veces
        return "decision"
    if not identity["verified"]:  # rechazo directo
        return "decision"
    if identity["confidence"] < get_settings().identity_confidence_threshold:  # escalamiento
        return "decision"
    return "risk_agent"


def after_risk(state: dict) -> str:
    risk = state.get("risk_result")
    if risk is None or risk["risk_level"] == "high":
        return "decision"
    return "documentation_agent"
