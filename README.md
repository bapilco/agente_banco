# Agente Orquestador de Onboarding Digital — Propuesta

> **Estado:** propuesta de diseño. Este documento describe qué se va a construir, cómo se organiza y por qué. Todavía no hay código.

## 1. Objetivo

Construir en **Python** un servicio HTTP que reciba una solicitud de onboarding de un prospecto y, mediante un **agente orquestador hecho con LangGraph**, coordine **4 agentes especializados** en **secuencia** (sin paralelismo):

| # | Agente | Responsabilidad | Herramientas permitidas |
|---|--------|-----------------|-------------------------|
| 1 | `IdentityAgent` (verificador) | Verificar la identidad del prospecto | `verify_identity` |
| 2 | `RiskAgent` (riesgo) | Consultar listas de riesgo (PEP, sanciones, etc.) | `check_risk_lists` |
| 3 | `DocumentationAgent` (documentación) | Preparar los documentos requeridos según las políticas del banco y el producto | `prepare_documentation` |
| 4 | `ResponseAgent` (respuesta) | Redactar la respuesta final al cliente | *ninguna* (solo lee el estado) |

El orquestador decide si el cliente es **apto**, **no apto** o **requiere escalamiento**. Cuando algo falla o es ambiguo, **propone una solución**.

---

## 2. Decisiones de diseño

### 2.1 Orquestación secuencial (sin paralelismo)
No tiene sentido consultar listas de riesgo si todavía no sabemos si la identidad es válida. Por eso el grafo es **lineal con aristas condicionales** que cortan el flujo en cuanto hay un resultado que impide continuar:

```
  POST ──▶ Validación de entrada (Pydantic, ANTES del grafo)
             │  document_id ≠ 10 dígitos / producto no soportado
             ├──────────────▶ HTTP 422 (no se invoca ningún agente)
             ▼ OK
              ┌──────────────────┐
              │ identity_agent   │──(verified=false / conf<0.8 /
              └────────┬─────────┘   falló 3 veces)───────────┐
                       ▼ verified=true y conf ≥ 0.8           │
              ┌──────────────────┐                            │
              │ risk_agent       │──(risk = high /            │
              └────────┬─────────┘   falló 3 veces)───────┐   │
                       ▼ low / medium                     │   │
              ┌──────────────────┐                        │   │
              │ documentation_   │──(falló 3 veces)───┐   │   │
              │ agent            │                    │   │   │
              └────────┬─────────┘                    ▼   ▼   ▼
                       │                     ┌──────────────────────────┐
                       └────────────────────▶│ decision (políticas)     │
                                             └────────────┬─────────────┘
                                                          ▼
                                             ┌──────────────────────────┐
                                             │ response_agent           │──▶ END
                                             └──────────────────────────┘
```

- La **validación de entrada ocurre antes de iniciar el proceso**: si `document_id` no son exactamente 10 dígitos numéricos (`^\d{10}$`) o el producto no está soportado, la API responde de inmediato con error y no se ejecuta ningún agente.
- **Nunca** se invoca a `risk_agent` si `identity_agent` no dio una verificación válida.
- **Nunca** se prepara documentación para un cliente con riesgo alto.
- Todos los caminos terminan en `decision` → `response_agent`, de forma que el cliente **siempre** recibe una respuesta coherente.

### 2.2 Control de herramientas por agente
Cada agente se construye con una **lista blanca** (`allowed_tools`) definida en el orquestador (`config/agents.yaml` / `agents/registry.py`). Si un agente intenta usar una herramienta fuera de su lista, la llamada se rechaza y se registra en la trazabilidad como `tool_not_allowed`. El LLM solo "ve" las herramientas que tiene permitidas.

### 2.3 Estado compartido entre pasos
Se usa un `TypedDict` de LangGraph (`OnboardingState`) que viaja por todos los nodos:

```text
request_id, prospect_name, document_id, product
identity_result   -> {verified, confidence}
risk_result       -> {risk_level, matches}
documentation     -> {required_documents: [...]}
decision          -> APPROVED | REJECTED | ESCALATED | ERROR
observations      -> [texto]  (p. ej. riesgo medium aprobado con observación)
escalations       -> [{reason, source_agent, suggested_action}]
errors            -> [{agent, attempts, last_error}]
trace             -> [{agent, attempt, status, started_at, duration_ms, tools_called}]
final_message     -> texto para el cliente
```

### 2.4 Reintentos (máximo 3 por agente)
Cada nodo de agente se envuelve con un decorador `with_retry(max_attempts=3)` en el orquestador:

1. Intento 1 → si falla (excepción, timeout, respuesta del LLM no parseable o fuera de esquema), se registra en `trace` con `status="failed"`.
2. Se reintenta al **mismo agente** (backoff corto: 0.5s, 1s).
3. Si los **3 intentos** fallan → se agrega un registro en `errors`, la decisión pasa a `ERROR` o `ESCALATED` y la API responde explicando qué agente falló y qué se propone (p. ej. "reintentar más tarde" o "revisión manual por un oficial").

Cada intento queda en la trazabilidad, así se ve exactamente cuántas veces se llamó a cada agente.

### 2.5 Escalamiento y mitigación de incertidumbre
Reglas (en `policies/onboarding_policy.py`, configurables):

| Condición | Resultado | Solución propuesta |
|-----------|-----------|--------------------|
| `verified = false` (sin importar `confidence`) | `REJECTED` (rechazo directo) | Solicitar al prospecto acudir a agencia con documento físico |
| `verified = true` y `confidence < 0.8` | `ESCALATED` | Verificación manual / biométrica adicional por un oficial |
| `risk_level = high` | `ESCALATED` | Revisión del oficial de cumplimiento (KYC reforzado) |
| `risk_level = medium` | `APPROVED` con observación (campo `observations`) | Debida diligencia ampliada (documentos extra) |
| `risk_level = low` | `APPROVED` | Continuar el proceso normal |
| Agente falla 3 veces | `ERROR` | Reintentar más tarde o derivar a atención manual |
| `document_id` ≠ 10 dígitos / producto no soportado | HTTP 422, antes del proceso | Corregir el documento / indicar productos válidos |

Todo escalamiento aparece en el campo `escalations` **y** en el `message` de la respuesta de la API.

> El LLM se usa para **interpretar y redactar** (razonamiento del agente, invocación de su herramienta y respuesta al cliente), pero la **decisión final de aptitud la toma código determinista** con las políticas. Así el resultado es auditable y no depende de que un modelo pequeño (qwen3:1.7b) "acierte".

---

## 3. Proveedor de LLM configurable (`.env`)

Un único archivo `.env` selecciona el proveedor:

```dotenv
# ollama | bedrock
LLM_PROVIDER=ollama

# --- Ollama (pruebas locales) ---
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:1.7b

# --- AWS Bedrock (modelo más barato de Anthropic: Claude Haiku 5.5) ---
AWS_REGION=us-east-1
BEDROCK_MODEL_ID=anthropic.claude-haiku-5-5
# Credenciales vía perfil AWS o variables estándar:
# AWS_PROFILE=default
# AWS_ACCESS_KEY_ID=...
# AWS_SECRET_ACCESS_KEY=...

# --- Orquestador ---
AGENT_MAX_RETRIES=3
AGENT_TIMEOUT_SECONDS=30
IDENTITY_CONFIDENCE_THRESHOLD=0.8
```

Se incluirá un `.env.example` en el repositorio; el `.env` real queda en `.gitignore`.

- **Ollama**: cliente `langchain-ollama` (`ChatOllama`) contra `qwen3:1.7b`.
- **Bedrock**: Claude Haiku 5.5 (`anthropic.claude-haiku-5-5`) es el modelo de Anthropic más económico de la línea actual. El precio en Bedrock lo define AWS (ver la página de precios de Bedrock). Se accederá con `langchain-aws` (`ChatBedrockConverse`) para mantener la misma interfaz de LangChain que con Ollama; el ID de modelo y la región quedan en `.env` por si en tu cuenta/región el modelo se expone con otro ID o prefijo de *inference profile* (p. ej. `us.`).

Una fábrica `llm/factory.py::get_chat_model()` lee `LLM_PROVIDER` y devuelve el modelo adecuado; ningún agente conoce el proveedor concreto.

---

## 4. API

### `POST /api/v1/onboarding/start`

**Request**
```json
{"prospect_name": "Juan Perez", "document_id": "1712345678", "product": "cuenta_ahorros"}
```

**Response (ejemplo con escalamiento)**
```json
{
  "request_id": "6f1c...",
  "status": "ESCALATED",
  "eligible": false,
  "message": "Estimado Juan Perez, su solicitud requiere una revisión adicional. ESCALAMIENTO: la verificación de identidad obtuvo una confianza de 0.72 (< 0.8). Solución propuesta: validación biométrica presencial con un oficial.",
  "escalations": [
    {"source_agent": "identity_agent", "reason": "confidence 0.72 < 0.8", "suggested_action": "Verificación manual/biométrica"}
  ],
  "required_documents": [],
  "errors": [],
  "trace": [
    {"agent": "identity_agent", "attempt": 1, "status": "failed",  "duration_ms": 1203, "tools_called": ["verify_identity"], "error": "timeout"},
    {"agent": "identity_agent", "attempt": 2, "status": "success", "duration_ms": 845,  "tools_called": ["verify_identity"]},
    {"agent": "response_agent", "attempt": 1, "status": "success", "duration_ms": 1530, "tools_called": []}
  ],
  "total_duration_ms": 3620
}
```

- `status`: `APPROVED` | `REJECTED` | `ESCALATED` | `ERROR`.
- `trace`: **qué agentes se llamaron, en qué orden, cuántos intentos y cuánto tardó cada llamada** (medido con `time.perf_counter`).
- Si un agente falló 3 veces, `errors` lo detalla y `message` explica la situación y la solución propuesta.

Endpoints auxiliares: `GET /health` (estado del servicio y proveedor LLM activo).

---

## 5. Herramientas mockeadas

Deterministas a partir del `document_id`, para poder probar todos los caminos sin servicios externos:

| Tool | Firma | Comportamiento mock |
|------|-------|---------------------|
| Tool 1 | `verify_identity(document_id)` → `{"verified": bool, "confidence": float}` | Según el último dígito del documento (ya validado como 10 dígitos): verificado con confianza alta, verificado con confianza < 0.8, o `verified: false` |
| Tool 2 | `check_risk_lists(name, document_id)` → `{"risk_level": "low/medium/high", "matches": []}` | Lista negra simulada (nombres/documentos en `data/risk_lists.json`) → `high` con *matches*; lista de observación → `medium`; resto → `low` |
| Tool 3 | `prepare_documentation(product, client_data)` → documentos requeridos | Lee `data/bank_policies.json` (por producto: `cuenta_ahorros`, `cuenta_corriente`, `tarjeta_credito`...) y agrega documentos extra si el riesgo es `medium` |

Se agregará además un modo de **inyección de fallos** (`MOCK_FAILURE_RATE` en `.env`, por defecto 0) para demostrar los reintentos.

---

## 6. Organización de carpetas

```
agente_banco/
├── README.md
├── instructions.md
├── .env.example                 # plantilla de configuración (Ollama / Bedrock)
├── .gitignore
├── pyproject.toml               # dependencias (o requirements.txt)
│
├── app/
│   ├── __init__.py
│   ├── main.py                  # creación de la app FastAPI
│   ├── config.py                # Settings (pydantic-settings) leídos desde .env
│   │
│   ├── api/
│   │   └── v1/
│   │       ├── routes_onboarding.py   # POST /api/v1/onboarding/start
│   │       └── schemas.py             # modelos Pydantic de request/response
│   │
│   ├── llm/
│   │   └── factory.py           # get_chat_model(): Ollama qwen3:1.7b | Bedrock Claude Haiku 5.5
│   │
│   ├── tools/                   # herramientas mockeadas
│   │   ├── identity.py          # verify_identity
│   │   ├── risk.py              # check_risk_lists
│   │   └── documentation.py     # prepare_documentation
│   │
│   ├── agents/                  # agentes especializados
│   │   ├── base.py              # clase base: LLM + allowed_tools + parseo de salida
│   │   ├── registry.py          # qué herramientas puede usar cada agente
│   │   ├── identity_agent.py
│   │   ├── risk_agent.py
│   │   ├── documentation_agent.py
│   │   ├── response_agent.py
│   │   └── prompts/             # system prompts de cada agente (.md)
│   │
│   ├── orchestrator/
│   │   ├── state.py             # OnboardingState (TypedDict)
│   │   ├── graph.py             # construcción del StateGraph de LangGraph
│   │   ├── nodes.py             # nodos: validate_input, decision, etc.
│   │   ├── routing.py           # aristas condicionales (cuándo cortar el flujo)
│   │   ├── retry.py             # with_retry(max_attempts=3)
│   │   └── tracing.py           # registro de trazabilidad y tiempos
│   │
│   └── policies/
│       └── onboarding_policy.py # reglas de aptitud, umbrales y soluciones propuestas
│
├── data/
│   ├── bank_policies.json       # documentos requeridos por producto
│   └── risk_lists.json          # listas de riesgo simuladas
│
└── tests/
    ├── test_tools.py
    ├── test_policy.py
    ├── test_retry.py            # fallos simulados: 1, 2 y 3 intentos
    ├── test_graph_flows.py      # aprobado / rechazado / escalado / error (LLM mockeado)
    └── test_api.py              # pruebas del endpoint con TestClient
```

---

## 7. Stack tecnológico

| Componente | Elección |
|-----------|----------|
| Lenguaje | Python 3.11+ |
| API | FastAPI + Uvicorn |
| Orquestación | LangGraph (`StateGraph`, aristas condicionales) |
| LLM local | Ollama + `qwen3:1.7b` (`langchain-ollama`) |
| LLM nube | AWS Bedrock + Claude Haiku 5.5 (`langchain-aws`) |
| Configuración | `python-dotenv` / `pydantic-settings` |
| Validación | Pydantic v2 |
| Pruebas | pytest |

---

## 8. Plan de trabajo

1. **Base del proyecto**: `pyproject.toml`, `.env.example`, `config.py`, fábrica de LLM.
2. **Tools mock** + datos (`bank_policies.json`, `risk_lists.json`) + pruebas unitarias.
3. **Políticas** de aptitud y escalamiento + pruebas.
4. **Agentes** con lista blanca de herramientas y salida estructurada.
5. **Orquestador LangGraph**: estado, nodos, ruteo secuencial, reintentos (3) y trazabilidad.
6. **API FastAPI** con el endpoint `POST /api/v1/onboarding/start`.
7. **Pruebas end-to-end** de los 4 escenarios (aprobado, rechazado, escalado, error tras 3 intentos), primero con Ollama local y luego con Bedrock.
8. Instrucciones de ejecución (`ollama pull qwen3:1.7b`, `uvicorn app.main:app`) y ejemplos `curl`.

---

## 9. Decisiones confirmadas

- **Productos soportados** para empezar: `cuenta_ahorros`, `cuenta_corriente`, `tarjeta_credito`.
- **`document_id`**: se valida **antes de iniciar el proceso** que sean exactamente 10 dígitos numéricos; si no, la API responde con error y no se llama a ningún agente.
- **Riesgo `medium`**: se **aprueba con observación** (se informa en `observations` y en el `message`, con los documentos adicionales requeridos).
- **`verified = false`**: **rechazo directo**, sin importar el valor de `confidence`. Solo si `verified = true` y `confidence < 0.8` se escala.
- **Persistencia**: no se requiere base de datos en esta fase; el estado vive durante la petición (estado de LangGraph en memoria).
