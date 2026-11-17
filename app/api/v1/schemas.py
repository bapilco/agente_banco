from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Product = Literal["cuenta_ahorros", "cuenta_corriente", "tarjeta_credito"]


class OnboardingRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    prospect_name: str = Field(..., min_length=3, max_length=120, examples=["Juan Perez"])
    document_id: str = Field(..., pattern=r"^\d{10}$", description="Exactamente 10 dígitos numéricos",
                             examples=["1712345678"])
    product: Product = Field(..., examples=["cuenta_ahorros"])


class TraceEntry(BaseModel):
    agent: str
    attempt: int
    status: Literal["success", "failed"]
    started_at: str
    duration_ms: float
    tools_called: list[str]
    error: Optional[str] = None
    notes: Optional[list[str]] = None


class Escalation(BaseModel):
    source_agent: str
    reason: str
    suggested_action: str


class AgentFailure(BaseModel):
    agent: str
    attempts: int
    message: str
    suggested_action: str


class OnboardingResponse(BaseModel):
    request_id: str
    status: Literal["APPROVED", "REJECTED", "ESCALATED", "ERROR"]
    eligible: bool
    message: str
    escalations: list[Escalation]
    observations: list[str]
    rejection_reasons: list[str]
    required_documents: list[str]
    identity_result: Optional[dict[str, Any]] = None
    risk_result: Optional[dict[str, Any]] = None
    errors: list[AgentFailure]
    trace: list[TraceEntry]
    total_duration_ms: float
    llm: dict[str, str]
