"""Grafo LangGraph del onboarding: secuencial, sin paralelismo entre agentes.

identity_agent -> [risk_agent -> [documentation_agent]] -> decision -> response_agent -> END
"""

import time
import uuid
from functools import lru_cache

from langgraph.graph import END, START, StateGraph

from app.config import get_settings
from app.orchestrator import routing
from app.orchestrator.nodes import build_agent_nodes, build_response_node, decision_node
from app.orchestrator.state import OnboardingState


def build_graph():
    graph = StateGraph(OnboardingState)
    for name, node in build_agent_nodes().items():
        graph.add_node(name, node)
    graph.add_node("decision", decision_node)
    graph.add_node("response_agent", build_response_node())

    graph.add_edge(START, "identity_agent")
    graph.add_conditional_edges("identity_agent", routing.after_identity, ["risk_agent", "decision"])
    graph.add_conditional_edges("risk_agent", routing.after_risk, ["documentation_agent", "decision"])
    graph.add_edge("documentation_agent", "decision")
    graph.add_edge("decision", "response_agent")
    graph.add_edge("response_agent", END)
    return graph.compile()


@lru_cache
def get_graph():
    return build_graph()


def run_onboarding(prospect_name: str, document_id: str, product: str) -> dict:
    request_id = str(uuid.uuid4())
    t0 = time.perf_counter()
    final = get_graph().invoke({
        "request_id": request_id,
        "prospect_name": prospect_name,
        "document_id": document_id,
        "product": product,
        "errors": [],
        "trace": [],
    })
    settings = get_settings()
    return {
        "request_id": request_id,
        "status": final["status"],
        "eligible": final["eligible"],
        "message": final["final_message"],
        "escalations": final.get("escalations", []),
        "observations": final.get("observations", []),
        "rejection_reasons": final.get("rejection_reasons", []),
        "required_documents": (final.get("documentation") or {}).get("required_documents", []),
        "identity_result": final.get("identity_result"),
        "risk_result": final.get("risk_result"),
        "errors": final.get("errors", []),
        "trace": final.get("trace", []),
        "total_duration_ms": round((time.perf_counter() - t0) * 1000, 2),
        "llm": {"provider": settings.llm_provider, "model": settings.llm_model_name},
    }
