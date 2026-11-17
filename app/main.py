from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.v1.routes_onboarding import router as onboarding_router
from app.config import get_settings

app = FastAPI(title="Agente Orquestador de Onboarding", version="1.0.0")
app.include_router(onboarding_router)

_FIELD_MESSAGES = {
    "document_id": "document_id debe contener exactamente 10 dígitos numéricos.",
    "product": "product debe ser uno de: cuenta_ahorros, cuenta_corriente, tarjeta_credito.",
    "prospect_name": "prospect_name es obligatorio (entre 3 y 120 caracteres).",
}


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    """La validación ocurre ANTES de iniciar el proceso: ningún agente se ejecuta."""
    details = []
    for err in exc.errors():
        field = str(err["loc"][-1]) if err.get("loc") else "body"
        details.append({"field": field, "message": _FIELD_MESSAGES.get(field, err.get("msg", "valor inválido"))})
    return JSONResponse(
        status_code=422,
        content={
            "status": "INVALID_REQUEST",
            "message": "La solicitud no cumple las validaciones de entrada; no se inició el proceso de onboarding.",
            "errors": details,
        },
    )


@app.get("/health")
def health() -> dict:
    settings = get_settings()
    return {"status": "ok", "llm_provider": settings.llm_provider, "llm_model": settings.llm_model_name}
