# Dragun

Dragun is an AI-powered personal consumption intelligence agent focused on **item-level awareness**:  
you log what you're about to buy, and Dragun tells you what you own, how your budget stands, and which constraints or patterns matter.

This repo contains a **Phase 1 implementation** using **Google Cloud ADK + Gemini Flash + Firestore**.

## Phase 1 delivered

- User registration (handle + passkey + zip code)
- Text-based item logging with natural language parsing
- Multi-tag assignment (agent/deterministic inference)
- Inventory state computation from append-only events
- Budget creation + budget status tracking
- Constraint creation + pre-purchase constraint evaluation
- ADK multi-agent graph:
  - `dragun_coordinator` (root)
  - `input_parser`
  - `inventory_agent`
  - `budget_agent`
  - `insight_agent`
- FastAPI app + local web UI
- Cloud Run-ready container and build config

## Tech stack

- Agent framework: `google-adk` (Python)
- Model: `gemini-flash-latest`
- Database: Cloud Firestore
- API/UI: FastAPI + HTML/CSS/JS
- Deployment: Cloud Run

## Project layout

```text
dragun/
  main.py
  agent_runtime.py
  config.py
  agents/
    graph.py
    toolkit.py
  services/
    parsing.py
    engine.py
  repositories/
    firestore_client.py
    users_repository.py
    events_repository.py
    budgets_repository.py
    adk_firestore_session_service.py
  schemas/
    models.py
  templates/index.html
  static/style.css
  static/app.js
Dockerfile
cloudbuild.yaml
requirements.txt
```

## Prerequisites

- Python 3.10+
- A Google Cloud project with Firestore enabled
- Gemini credentials (Google API key or Vertex AI auth)
- ADC configured locally (recommended):
  - `gcloud auth application-default login`

## Environment configuration

Copy and edit:

```bash
cp .env.example .env
```

Key variables:

- `GOOGLE_CLOUD_PROJECT`
- `GOOGLE_CLOUD_LOCATION` (for Vertex path)
- `GOOGLE_GENAI_USE_VERTEXAI=TRUE` (Vertex) or `FALSE` (AI Studio key path)
- `GOOGLE_API_KEY` (if using AI Studio key path)
- `FIRESTORE_DATABASE` (`(default)` for most projects)
- `DRAGUN_MODEL=gemini-flash-latest`

## Run locally

Install deps:

```bash
python3 -m pip install --ignore-installed -r requirements.txt
```

Start app:

```bash
uvicorn dragun.main:app --host 0.0.0.0 --port 8080
```

Open:

- UI: `http://localhost:8080/`
- Health: `http://localhost:8080/healthz`

## API quickstart

Register:

```bash
curl -s -X POST http://localhost:8080/api/register \
  -H "Content-Type: application/json" \
  -d '{"handle":"sam","passkey":"dragon123","zip_code":"94107"}'
```

Create budget:

```bash
curl -s -X POST http://localhost:8080/api/budgets \
  -H "Content-Type: application/json" \
  -d '{
    "handle":"sam",
    "passkey":"dragon123",
    "budget_scope":"clothing",
    "scope_tags":["clothing"],
    "budget_amount":200,
    "period_type":"monthly"
  }'
```

Log purchase:

```bash
curl -s -X POST http://localhost:8080/api/chat \
  -H "Content-Type: application/json" \
  -d '{"handle":"sam","passkey":"dragon123","message":"3 shirts, 2 dresses, 1 pant - 50 bucks"}'
```

Create constraint:

```bash
curl -s -X POST http://localhost:8080/api/constraints \
  -H "Content-Type: application/json" \
  -d '{
    "handle":"sam",
    "passkey":"dragon123",
    "constraint_type":"inventory_cap",
    "scope_tags":["clothing"],
    "operator":"count_exceeds",
    "threshold_value":15
  }'
```

## Deploy to Cloud Run

Build:

```bash
gcloud builds submit --config cloudbuild.yaml \
  --substitutions _IMAGE=us-central1-docker.pkg.dev/$GOOGLE_CLOUD_PROJECT/dragun/dragun:latest
```

Deploy:

```bash
gcloud run deploy dragun \
  --image us-central1-docker.pkg.dev/$GOOGLE_CLOUD_PROJECT/dragun/dragun:latest \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars GOOGLE_CLOUD_PROJECT=$GOOGLE_CLOUD_PROJECT,GOOGLE_CLOUD_LOCATION=us-central1,GOOGLE_GENAI_USE_VERTEXAI=TRUE,DRAGUN_MODEL=gemini-flash-latest,FIRESTORE_DATABASE='(default)'
```

## Notes

- Core business data is persisted in Firestore (`users`, `events`, `budgets`, `constraints`).
- ADK session data is persisted with a custom Firestore-backed `BaseSessionService`.
- If Gemini auth is unavailable, the app falls back to deterministic local behavior for core item logging and budget/constraint commands.
