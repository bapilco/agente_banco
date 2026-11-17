from fastapi import APIRouter

from app.api.v1.schemas import OnboardingRequest, OnboardingResponse
from app.orchestrator.graph import run_onboarding

router = APIRouter(prefix="/api/v1/onboarding", tags=["onboarding"])


@router.post("/start", response_model=OnboardingResponse)
def start_onboarding(request: OnboardingRequest) -> dict:
    # Endpoint síncrono: FastAPI lo ejecuta en un threadpool, sin bloquear el event loop.
    return run_onboarding(request.prospect_name, request.document_id, request.product)
