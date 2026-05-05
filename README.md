# Dragun

Dragun is a Phase 1 Google Cloud ADK Python agent for item-level consumption
intelligence. It keeps an immutable Firestore event log, derives inventory and
budget views from events, and responds through a concise dragon persona.

## What is included

- Google Cloud ADK agent graph with the PRD sub-agents:
  - `dragun_coordinator`
  - `input_parser`
  - `inventory_agent`
  - `budget_agent`
  - `insight_agent`
- Gemini Flash model configuration (`gemini-flash-latest` by default)
- Firestore persistence for users, events, tags, event_tags, budgets, and constraints
- FastAPI app with a local web chat UI
- Phase 1 workflows:
  - handle/passkey/zip registration
  - text item logging with quantity, cost, lifespan, and inferred tags
  - inventory computation from the event stream
  - budget creation and live budget status
  - inventory cap, hard budget, and pace constraint checks

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
uvicorn dragun.app:app --reload
```

Open http://localhost:8000.

If `GOOGLE_CLOUD_PROJECT` is unset, Dragun uses in-memory storage for local demos.
Set `GOOGLE_CLOUD_PROJECT` to use Firestore. For local Firestore emulator usage,
set `FIRESTORE_EMULATOR_HOST`.

## Environment

```bash
GOOGLE_CLOUD_PROJECT=your-project-id
FIRESTORE_DATABASE=(default)
GOOGLE_API_KEY=optional-gemini-api-key
ADK_MODEL=gemini-flash-latest
DRAGUN_PASSKEY_SALT=change-me
```

The deterministic parser keeps Phase 1 runnable without Gemini credentials; when
`GOOGLE_API_KEY` is present, the parser first attempts Gemini Flash structured
parsing and falls back safely.

## Deploy to Cloud Run

```bash
gcloud builds submit --tag gcr.io/$GOOGLE_CLOUD_PROJECT/dragun
gcloud run deploy dragun \
  --image gcr.io/$GOOGLE_CLOUD_PROJECT/dragun \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars GOOGLE_CLOUD_PROJECT=$GOOGLE_CLOUD_PROJECT,ADK_MODEL=gemini-flash-latest
```

The included `cloudrun.yaml` can also be adapted for service-based deployment.

## API quick start

```bash
curl -X POST http://localhost:8000/api/register \
  -H 'content-type: application/json' \
  -d '{"handle":"ember","passkey":"secret-passkey","zip_code":"12345"}'

curl -X POST http://localhost:8000/api/chat \
  -H 'content-type: application/json' \
  -d '{"user_id":"USER_ID","message":"budget 100 for clothing this month"}'

curl -X POST http://localhost:8000/api/chat \
  -H 'content-type: application/json' \
  -d '{"user_id":"USER_ID","message":"3 shirts, 2 dresses, 1 pant - 50 bucks"}'
```
