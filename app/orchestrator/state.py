"""Estado compartido entre los nodos del grafo de onboarding."""

import operator
from typing import Annotated, Optional, TypedDict


class OnboardingState(TypedDict, total=False):
    # Entrada (ya validada por la API)
    request_id: str
    prospect_name: str
    document_id: str
    product: str

    # Resultados de los agentes
    identity_result: Optional[dict]
    risk_result: Optional[dict]
    documentation: Optional[dict]

    # Decisión
    status: str
    eligible: bool
    rejection_reasons: list[str]
    escalations: list[dict]
    observations: list[str]
    final_message: str

    # Acumulativos (cada nodo agrega, nunca sobrescribe)
    errors: Annotated[list[dict], operator.add]
    trace: Annotated[list[dict], operator.add]
