"""Nodos del grafo. Cada nodo de agente se ejecuta a través de run_with_retry."""

from app.agents.documentation_agent import DocumentationAgent
from app.agents.identity_agent import IdentityAgent
from app.agents.response_agent import ResponseAgent
from app.agents.risk_agent import RiskAgent
from app.config import get_settings
from app.orchestrator.retry import run_with_retry
from app.policies import onboarding_policy as policy


def _agent_node(agent, result_key: str):
    def node(state: dict) -> dict:
        outcome = run_with_retry(agent, state)
        update = {
            result_key: outcome.output.result if outcome.output else None,
            "trace": outcome.trace,
            "errors": [outcome.error] if outcome.error else [],
        }
        return update

    node.__name__ = f"{agent.name}_node"
    return node


def build_agent_nodes() -> dict:
    return {
        "identity_agent": _agent_node(IdentityAgent(), "identity_result"),
        "risk_agent": _agent_node(RiskAgent(), "risk_result"),
        "documentation_agent": _agent_node(DocumentationAgent(), "documentation"),
    }


def decision_node(state: dict) -> dict:
    outcome = policy.evaluate(state, get_settings().identity_confidence_threshold)
    return {
        "status": outcome.status,
        "eligible": outcome.eligible,
        "escalations": outcome.escalations,
        "observations": outcome.observations,
        "rejection_reasons": outcome.rejection_reasons,
    }


_FALLBACK_MESSAGES = {
    policy.APPROVED: "Estimado/a {name}, su solicitud de {product} ha sido aprobada. "
                     "Por favor presente los documentos requeridos para completar la apertura.",
    policy.REJECTED: "Estimado/a {name}, lamentamos informarle que su solicitud de {product} "
                     "no ha podido ser aprobada en este momento.",
    policy.ESCALATED: "Estimado/a {name}, su solicitud de {product} requiere una revisión adicional "
                      "por parte de nuestro equipo. Le contactaremos con los siguientes pasos.",
    policy.ERROR: "Estimado/a {name}, no pudimos completar su solicitud de {product} por un "
                  "inconveniente técnico. Por favor intente nuevamente más tarde.",
}


def _compose_message(base_text: str, state: dict, errors: list[dict]) -> str:
    """Agrega de forma determinista escalamientos, observaciones y errores al mensaje del cliente,
    para que nunca dependan de que el LLM los mencione."""
    parts = [base_text.strip()]
    for esc in state.get("escalations", []):
        parts.append(f"ESCALAMIENTO: {esc['reason']} Solución propuesta: {esc['suggested_action']}")
    for obs in state.get("observations", []):
        parts.append(f"OBSERVACIÓN: {obs}")
    for err in errors:
        parts.append(f"ERROR: {err['message']} Solución propuesta: {err['suggested_action']}")
    return "\n\n".join(parts)


def build_response_node():
    agent = ResponseAgent()

    def response_node(state: dict) -> dict:
        outcome = run_with_retry(agent, state)
        new_errors = [outcome.error] if outcome.error else []
        if outcome.output:
            text = outcome.output.result
        else:
            text = _FALLBACK_MESSAGES[state["status"]].format(
                name=state["prospect_name"], product=state["product"].replace("_", " ")
            )
        all_errors = list(state.get("errors", [])) + new_errors
        return {
            "final_message": _compose_message(text, state, all_errors),
            "trace": outcome.trace,
            "errors": new_errors,
        }

    return response_node
