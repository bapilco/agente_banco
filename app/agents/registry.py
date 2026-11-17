"""Control de herramientas: qué tools puede usar cada agente (lista blanca del orquestador)."""

AGENT_ALLOWED_TOOLS: dict[str, list[str]] = {
    "identity_agent": ["verify_identity"],
    "risk_agent": ["check_risk_lists"],
    "documentation_agent": ["prepare_documentation"],
    "response_agent": [],  # solo redacta a partir del estado; no usa herramientas
}


def allowed_tools_for(agent_name: str) -> list[str]:
    return list(AGENT_ALLOWED_TOOLS.get(agent_name, []))
