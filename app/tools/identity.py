from app.tools._common import maybe_fail


def verify_identity(document_id: str) -> dict:
    """Tool 1 (mock): verifica la identidad del prospecto contra el registro civil.

    Regla del mock según el último dígito del documento (ya validado como 10 dígitos):
      - 0 o 1 -> no verificado (confianza 0.35)
      - 2 o 3 -> verificado con confianza baja (0.65) -> requiere escalamiento
      - 4 a 9 -> verificado con confianza alta (0.95)
    """
    maybe_fail("verify_identity")
    last = int(document_id[-1])
    if last in (0, 1):
        return {"verified": False, "confidence": 0.35}
    if last in (2, 3):
        return {"verified": True, "confidence": 0.65}
    return {"verified": True, "confidence": 0.95}
