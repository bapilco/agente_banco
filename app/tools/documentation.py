from app.tools._common import ToolExecutionError, load_json, maybe_fail


def prepare_documentation(product: str, client_data: dict) -> dict:
    """Tool 3 (mock): prepara los documentos requeridos según las políticas del banco."""
    maybe_fail("prepare_documentation")
    policies = load_json("bank_policies.json")

    product_policy = policies["products"].get(product)
    if product_policy is None:
        raise ToolExecutionError(f"prepare_documentation: producto sin política definida: {product}")

    documents = list(product_policy["required_documents"])
    if client_data.get("risk_level") == "medium":
        documents += policies["enhanced_due_diligence_documents"]

    return {
        "product": product,
        "product_name": product_policy["display_name"],
        "required_documents": documents,
    }
