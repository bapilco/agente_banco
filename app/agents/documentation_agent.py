from app.agents.base import AgentError, ToolAgent


class DocumentationAgent(ToolAgent):
    name = "documentation_agent"
    prompt_name = "documentation_agent"

    def build_input(self, state: dict) -> str:
        risk = (state.get("risk_result") or {}).get("risk_level", "desconocido")
        return (
            f"Prepara la documentación requerida.\n"
            f"product: {state['product']}\n"
            f"client_data: nombre={state['prospect_name']}, document_id={state['document_id']}, "
            f"risk_level={risk}"
        )

    def trusted_args(self, state: dict) -> dict:
        return {
            "product": state["product"],
            "client_data": {
                "name": state["prospect_name"],
                "document_id": state["document_id"],
                "risk_level": (state.get("risk_result") or {}).get("risk_level"),
            },
        }

    def validate_result(self, result: dict) -> dict:
        docs = result.get("required_documents")
        if not isinstance(docs, list) or not docs:
            raise AgentError("documentation_agent: no se obtuvieron documentos requeridos")
        return result
