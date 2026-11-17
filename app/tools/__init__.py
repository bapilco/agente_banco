"""Herramientas mockeadas. El registro TOOLS es la única forma en que los agentes acceden a ellas."""

from app.tools.documentation import prepare_documentation
from app.tools.identity import verify_identity
from app.tools.risk import check_risk_lists

TOOLS = {
    "verify_identity": verify_identity,
    "check_risk_lists": check_risk_lists,
    "prepare_documentation": prepare_documentation,
}

__all__ = ["TOOLS", "verify_identity", "check_risk_lists", "prepare_documentation"]
