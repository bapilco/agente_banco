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

---

## 10. Cómo ejecutar

### Instalación
```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (Linux/Mac: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env          # Windows  (Linux/Mac: cp .env.example .env)
ollama pull qwen3:1.7b          # solo si LLM_PROVIDER=ollama
```

### Iniciar el servicio con Uvicorn
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
Documentación interactiva (Swagger): http://localhost:8000/docs · Salud del servicio: http://localhost:8000/health

### Ejemplo con curl
```bash
curl -X POST http://localhost:8000/api/v1/onboarding/start \
  -H "Content-Type: application/json" \
  -d '{"prospect_name": "Juan Perez", "document_id": "1712345678", "product": "cuenta_ahorros"}'
```

En **PowerShell** usa `curl.exe` (no el alias `curl`) y escapa las comillas:
```powershell
curl.exe -X POST http://localhost:8000/api/v1/onboarding/start -H "Content-Type: application/json" -d '{\"prospect_name\": \"Juan Perez\", \"document_id\": \"1712345678\", \"product\": \"cuenta_ahorros\"}'
```

### Datos de prueba (mocks) para cada escenario
| Escenario | `prospect_name` | `document_id` | Resultado esperado |
|-----------|-----------------|---------------|--------------------|
| Aprobado | Juan Perez | 1712345678 | `APPROVED` |
| Aprobado con observación (riesgo medio) | Maria Observada | 1755555555 | `APPROVED` + `observations` |
| Escalado por riesgo alto | Carlos Riesgo Alto | 1799999999 | `ESCALATED` |
| Escalado por confianza < 0.8 | Juan Perez | 1712345672 | `ESCALATED` |
| Rechazo directo (no verificado) | Juan Perez | 1712345670 | `REJECTED` |
| Validación previa (no son 10 dígitos) | Juan Perez | 12345 | HTTP 422, no se ejecuta ningún agente |
| Reintentos / error tras 3 intentos | cualquiera | cualquiera | Configurar `MOCK_FAILURE_RATE=0.5` (o `1.0`) en `.env` |

---

## 11. Despliegue en AWS (Lambda + API Gateway + Bedrock)

La misma app FastAPI se encapsula en **AWS Lambda** (con el adaptador [Mangum](https://github.com/Kludex/mangum)) y se expone con **Amazon API Gateway (HTTP API)**. La infraestructura está definida con **AWS SAM** en `template.yaml`.

```
Cliente ──HTTPS──▶ API Gateway (HTTP API) ──▶ Lambda (imagen de contenedor)
                                               │  FastAPI + Mangum
                                               │  LangGraph (orquestador + agentes)
                                               └──▶ Amazon Bedrock (Claude Haiku 5.5)
```

### Archivos de despliegue
| Archivo | Propósito |
|---------|-----------|
| `template.yaml` | Plantilla SAM: Lambda, HTTP API, rutas, IAM para Bedrock, logs y variables de ambiente |
| `Dockerfile` | Imagen de la Lambda (`public.ecr.aws/lambda/python:3.12`) |
| `requirements-lambda.txt` | Dependencias de la nube (sin Ollama, Uvicorn ni pytest) |
| `app/lambda_handler.py` | Handler de Lambda: `Mangum(app)` |
| `.dockerignore` | Excluye `.env`, `.venv`, `tests`, etc. de la imagen |

Se usa **imagen de contenedor** (no .zip) porque las dependencias (LangGraph, LangChain, pydantic-core) incluyen binarios nativos y pesan más que el límite de un .zip; además se construyen para Linux aunque se despliegue desde Windows.

### Variables de ambiente en la nube
Las define `template.yaml`. **En la nube el LLM siempre es Bedrock**:

| Variable | Valor | Origen |
|----------|-------|--------|
| `LLM_PROVIDER` | `bedrock` | fijo en la plantilla |
| `BEDROCK_MODEL_ID` | `anthropic.claude-haiku-5-5` | parámetro `BedrockModelId` |
| `AGENT_MAX_RETRIES` | `3` | fijo |
| `AGENT_TIMEOUT_SECONDS` | `8` | parámetro `AgentTimeoutSeconds` |
| `AGENT_RETRY_BACKOFF_SECONDS` | `0.3` | parámetro |
| `IDENTITY_CONFIDENCE_THRESHOLD` | `0.8` | parámetro |
| `MOCK_FAILURE_RATE` | `0` | parámetro |
| `AWS_REGION` | región del stack | la define Lambda automáticamente (variable reservada) |

El archivo `.env` **no** se incluye en la imagen; solo se usa en local.

### Permisos IAM
La Lambda solo puede invocar el modelo configurado (`bedrock:InvokeModel` y `bedrock:InvokeModelWithResponseStream`) sobre el *foundation model* y sus *inference profiles*.

### Requisitos previos
1. [AWS CLI](https://docs.aws.amazon.com/cli/) configurado (`aws configure`) y [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html) instalado.
2. Docker en ejecución.
3. Acceso habilitado a **Claude Haiku 5.5** en la consola de Amazon Bedrock, en la región donde se despliega.

### Comandos
```bash
# Construir la imagen
sam build

# Primer despliegue (guiado: nombre del stack, región, parámetros; crea el repositorio ECR)
sam deploy --guided --resolve-image-repos --capabilities CAPABILITY_IAM

# Despliegues posteriores (usa samconfig.toml generado por --guided)
sam deploy
```

Si tu cuenta requiere *inference profile*, sobreescribe el ID del modelo:
```bash
sam deploy --parameter-overrides BedrockModelId=us.anthropic.claude-haiku-5-5
```

Al terminar, SAM muestra las salidas `ApiBaseUrl` y `OnboardingEndpoint`.

### Probar en la nube
```bash
curl -X POST https://<api-id>.execute-api.<region>.amazonaws.com/api/v1/onboarding/start \
  -H "Content-Type: application/json" \
  -d '{"prospect_name": "Juan Perez", "document_id": "1712345678", "product": "cuenta_ahorros"}'
```

Ver logs:
```bash
sam logs --stack-name <nombre-del-stack> --tail
```

Eliminar el stack:
```bash
sam delete
```

### Consideraciones
- **Límite de 30 s de API Gateway:** la integración de HTTP API se corta a los 30 s. Por eso en la nube `AGENT_TIMEOUT_SECONDS=8`. En el peor caso (varios agentes reintentando 3 veces) el flujo puede superar ese límite y API Gateway respondería 503 aunque la Lambda termine. Si se necesita más margen, la alternativa es un flujo asíncrono (devolver `request_id` y consultar el resultado después).
- **Autenticación:** la plantilla expone la API sin autorizador y solo con *throttling* (`ThrottlingRateLimit`/`ThrottlingBurstLimit`). Para un ambiente real se recomienda agregar un autorizador JWT/Cognito o IAM.
- **Arranque en frío:** la primera invocación tarda más por la carga de la imagen y las librerías.
