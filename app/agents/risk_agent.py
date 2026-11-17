from app.agents.base import AgentError, ToolAgent


class RiskAgent(ToolAgent):
    name = "risk_agent"
    prompt_name = "risk_agent"

    def build_input(self, state: dict) -> str:
        return (
            f"Consulta las listas de riesgo para el prospecto.\n"
            f"name: {state['prospect_name']}\n"
            f"document_id: {state['document_id']}"
        )

    def trusted_args(self, state: dict) -> dict:
        return {"name": state["prospect_name"], "document_id": state["document_id"]}

    def validate_result(self, result: dict) -> dict:
        if result.get("risk_level") not in ("low", "medium", "high"):
            raise AgentError("risk_agent: 'risk_level' inválido")
        if not isinstance(result.get("matches"), list):
            raise AgentError("risk_agent: 'matches' debe ser una lista")
        return result
