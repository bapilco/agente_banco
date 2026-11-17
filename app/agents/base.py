"""Clase base de los agentes especializados."""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool

from app.agents.registry import allowed_tools_for
from app.llm import factory
from app.tools import TOOLS

PROMPTS_DIR = Path(__file__).parent / "prompts"
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


class AgentError(RuntimeError):
    """El agente no pudo completar su tarea (respuesta inválida del LLM, tool fallida, etc.)."""


class ToolNotAllowedError(AgentError):
    """El agente intentó usar una herramienta fuera de su lista blanca."""


@dataclass
class AgentOutput:
    result: Any
    tools_called: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def message_text(message) -> str:
    """Texto de un AIMessage, sea su contenido un string o una lista de bloques (Bedrock)."""
    content = getattr(message, "content", "")
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content if isinstance(b, dict))
    return content or ""


def clean_llm_text(text: str) -> str:
    """Elimina bloques <think> (qwen3) y espacios sobrantes."""
    return _THINK_RE.sub("", text or "").strip()


class ToolAgent:
    """Agente que usa el LLM para decidir la invocación de su (única) herramienta permitida.

    Controles del orquestador:
      * El LLM solo recibe las herramientas de su lista blanca.
      * Si pide una herramienta no permitida -> ToolNotAllowedError (cuenta como fallo y se reintenta).
      * Los argumentos se toman del estado validado, no de lo que generó el LLM, para evitar
        alucinaciones o inyección de datos. Si difieren, se deja nota en la trazabilidad.
    """

    name: str = ""
    prompt_name: str = ""

    def __init__(self) -> None:
        self.allowed_tools = allowed_tools_for(self.name)
        self.system_prompt = load_prompt(self.prompt_name)

    # --- a implementar por cada agente ---
    def build_input(self, state: dict) -> str:
        raise NotImplementedError

    def trusted_args(self, state: dict) -> dict:
        raise NotImplementedError

    def validate_result(self, result: dict) -> dict:
        return result

    # --- flujo común ---
    def _lc_tools(self) -> list[StructuredTool]:
        return [StructuredTool.from_function(TOOLS[name], name=name) for name in self.allowed_tools]

    def run(self, state: dict) -> AgentOutput:
        llm = factory.get_chat_model().bind_tools(self._lc_tools())
        response = llm.invoke(
            [SystemMessage(content=self.system_prompt), HumanMessage(content=self.build_input(state))]
        )

        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            raise AgentError(f"{self.name}: el LLM no invocó ninguna herramienta")

        call = tool_calls[0]
        tool_name = call["name"]
        if tool_name not in self.allowed_tools:
            err = ToolNotAllowedError(f"{self.name}: herramienta no permitida '{tool_name}'")
            err.tools_called = [tool_name]
            raise err

        args = self.trusted_args(state)
        notes = []
        llm_args = call.get("args") or {}
        differs = [k for k, v in args.items() if isinstance(v, str) and k in llm_args and llm_args[k] != v]
        if differs:
            notes.append(f"args_overridden({', '.join(differs)}): se usaron los datos validados del estado")

        try:
            result = self.validate_result(TOOLS[tool_name](**args))
        except AgentError as exc:
            exc.tools_called = [tool_name]
            raise
        except Exception as exc:
            err = AgentError(f"{type(exc).__name__}: {exc}")
            err.tools_called = [tool_name]
            raise err from exc
        return AgentOutput(result=result, tools_called=[tool_name], notes=notes)
