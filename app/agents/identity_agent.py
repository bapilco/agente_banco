from app.agents.base import AgentError, ToolAgent


class IdentityAgent(ToolAgent):
    name = "identity_agent"
    prompt_name = "identity_agent"

    def build_input(self, state: dict) -> str:
        return (
            f"Verifica la identidad del prospecto.\n"
            f"Nombre: {state['prospect_name']}\n"
            f"document_id: {state['document_id']}"
        )

    def trusted_args(self, state: dict) -> dict:
        return {"document_id": state["document_id"]}

    def validate_result(self, result: dict) -> dict:
        if not isinstance(result.get("verified"), bool):
            raise AgentError("identity_agent: respuesta sin campo 'verified' válido")
        conf = result.get("confidence")
        if not isinstance(conf, (int, float)) or not 0.0 <= conf <= 1.0:
            raise AgentError("identity_agent: 'confidence' fuera de rango [0, 1]")
        return {"verified": result["verified"], "confidence": float(conf)}
