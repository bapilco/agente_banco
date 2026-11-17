"""Políticas de aptitud del banco. La decisión final es determinista y auditable (no la toma el LLM)."""

from dataclasses import dataclass, field

APPROVED = "APPROVED"
REJECTED = "REJECTED"
ESCALATED = "ESCALATED"
ERROR = "ERROR"

SUPPORTED_PRODUCTS = ("cuenta_ahorros", "cuenta_corriente", "tarjeta_credito")

# Solución propuesta cuando un agente falla todos sus intentos.
FAILURE_ACTIONS = {
    "identity_agent": "Reintentar la solicitud más tarde o realizar la verificación de identidad presencial en agencia.",
    "risk_agent": "Derivar a revisión manual del oficial de cumplimiento antes de continuar el onboarding.",
    "documentation_agent": "Un asesor contactará al prospecto para indicarle manualmente los documentos requeridos.",
    "response_agent": "Se usó un mensaje predeterminado; revisar disponibilidad del modelo de lenguaje.",
}


@dataclass
class PolicyOutcome:
    status: str
    eligible: bool
    escalations: list[dict] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    rejection_reasons: list[str] = field(default_factory=list)


def _failed(state: dict, agent: str) -> bool:
    return any(e["agent"] == agent for e in state.get("errors", []))


def evaluate(state: dict, confidence_threshold: float = 0.8) -> PolicyOutcome:
    """Evalúa el estado acumulado en el orden en que se ejecutaron los agentes."""
    identity = state.get("identity_result")
    risk = state.get("risk_result")

    # 1. Identidad
    if _failed(state, "identity_agent") or identity is None:
        return PolicyOutcome(status=ERROR, eligible=False)
    if not identity["verified"]:
        # Rechazo directo, sin importar la confianza.
        return PolicyOutcome(
            status=REJECTED,
            eligible=False,
            rejection_reasons=["No fue posible verificar la identidad del prospecto."],
        )
    if identity["confidence"] < confidence_threshold:
        return PolicyOutcome(
            status=ESCALATED,
            eligible=False,
            escalations=[{
                "source_agent": "identity_agent",
                "reason": f"Confianza de verificación de identidad {identity['confidence']:.2f} "
                          f"menor al umbral {confidence_threshold:.2f}.",
                "suggested_action": "Verificación manual/biométrica adicional por un oficial del banco.",
            }],
        )

    # 2. Riesgo
    if _failed(state, "risk_agent") or risk is None:
        return PolicyOutcome(status=ERROR, eligible=False)
    if risk["risk_level"] == "high":
        lists = sorted({m.get("list", "N/D") for m in risk.get("matches", [])})
        return PolicyOutcome(
            status=ESCALATED,
            eligible=False,
            escalations=[{
                "source_agent": "risk_agent",
                "reason": f"Nivel de riesgo ALTO (coincidencias en: {', '.join(lists) or 'N/D'}).",
                "suggested_action": "Revisión del oficial de cumplimiento con debida diligencia reforzada (KYC reforzado).",
            }],
        )

    # 3. Documentación
    if _failed(state, "documentation_agent") or state.get("documentation") is None:
        return PolicyOutcome(status=ERROR, eligible=False)

    observations = []
    if risk["risk_level"] == "medium":
        observations.append(
            "Aprobado con observación: nivel de riesgo MEDIO. Se aplica debida diligencia ampliada "
            "y se requieren documentos adicionales de origen de fondos."
        )
    return PolicyOutcome(status=APPROVED, eligible=True, observations=observations)
