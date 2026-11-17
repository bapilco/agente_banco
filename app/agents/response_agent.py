import json

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.base import AgentError, AgentOutput, clean_llm_text, load_prompt, message_text
from app.llm import factory


class ResponseAgent:
    """Redacta el mensaje al cliente. No tiene herramientas: solo lee la decisión ya tomada."""

    name = "response_agent"

    def __init__(self) -> None:
        self.system_prompt = load_prompt("response_agent")

    def run(self, state: dict) -> AgentOutput:
        facts = {
            "nombre": state["prospect_name"],
            "producto": state["product"],
            "estado": state.get("status"),
            "motivos_rechazo": state.get("rejection_reasons", []),
            "escalamientos": [e["reason"] for e in state.get("escalations", [])],
            "observaciones": state.get("observations", []),
            "documentos_requeridos": (state.get("documentation") or {}).get("required_documents", []),
            "errores": [e["message"] for e in state.get("errors", [])],
        }
        response = factory.get_chat_model().invoke(
            [
                SystemMessage(content=self.system_prompt),
                HumanMessage(content=json.dumps(facts, ensure_ascii=False, indent=2)),
            ]
        )
        text = clean_llm_text(message_text(response))
        if len(text) < 20:
            raise AgentError("response_agent: el LLM devolvió un mensaje vacío o demasiado corto")
        return AgentOutput(result=text)
