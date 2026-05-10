# 🐉 Dragun

**Personal consumption intelligence — powered by Gemini 2.5 Flash, Google Cloud Run, and Arize Phoenix.**

> Try it live: **[mydragun.com](https://mydragun.com)**

Dragun is your personal dragon that guards your hoard. Tell it what you bought, what you own, and what limits you want to set — it tracks everything, surfaces patterns, and keeps you honest without moralizing.

Built for the [Google Cloud Rapid Agent Hackathon](https://rapid-agent.devpost.com/) — Arize track.

---

## How it works

- **Gemini 2.5 Flash** turns messy user input into strict JSON intents, then Python performs the backend work
- **Firestore** stores an immutable event log; inventory and budget views are derived from events
- **Arize Phoenix** traces every Gemini call for observability (latency, token counts, tool usage)
- **Google Cloud Run** hosts the app at [mydragun.com](https://mydragun.com)

Dragun now uses a thin-agent / fat-backend loop:

1. User text or browser voice transcript comes in.
2. Gemini extracts a compact JSON intent, or the deterministic parser falls back.
3. Python validates the intent, routes it to backend handlers, queries Firestore, and computes budget/advice bands.
4. Gemini may phrase the final response from compact backend facts only.

Examples:

| What you say | What Dragun does |
|---|---|
| "I bought 3 shirts for $50" | `log_purchase` → updates inventory + budget |
| "I have 12 shirts already" | `set_inventory_baseline` → sets starting state |
| "What do I own?" | `get_inventory` → returns full hoard |
| "Budget $200 for clothing" | `set_budget` → creates monthly budget |
| "Cap me at 10 shirts" | `set_inventory_cap` → sets guard |
| "How's my budget?" | `get_budget_status` → shows remaining + pace |

---

## Stack

- **Agent**: `google-genai` SDK with Gemini 2.5 Flash JSON extraction + advice phrasing
- **Observability**: Arize Phoenix (`arize-phoenix-otel` + `openinference-instrumentation-google-genai`)
- **Storage**: Google Cloud Firestore (Native mode)
- **API**: FastAPI + Uvicorn
- **Hosting**: Google Cloud Run (`us-central1`)
- **License**: MIT

---

## Local setup

```bash
git clone https://github.com/YOUR_USERNAME/dragun.git
cd dragun_project
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # add your GOOGLE_API_KEY
uvicorn dragun.app:app --reload
```

Open http://localhost:8000.

Without `GOOGLE_API_KEY`, Dragun falls back to a deterministic parser. Without `GOOGLE_CLOUD_PROJECT`, it uses in-memory storage.

---

## Environment variables

```bash
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
DRAGUN_USE_FIRESTORE=true
FIRESTORE_DATABASE=(default)
ADK_MODEL=gemini-2.5-flash
GOOGLE_API_KEY=your-gemini-api-key        # from aistudio.google.com
ARIZE_API_KEY=your-arize-api-key          # from app.phoenix.arize.com
DRAGUN_PASSKEY_SALT=random-hex-string     # never change after first deploy
DRAGUN_SESSION_SECRET=random-hex-string   # signs browser session tokens
CORS_ORIGINS=["*"]
```

---

## Deploy to Cloud Run

```bash
bash deploy.sh <GCP_PROJECT_ID> <GEMINI_API_KEY> [PASSKEY_SALT] [ARIZE_API_KEY]
```

The script handles: enabling APIs, Artifact Registry, Firestore setup, Docker build, and Cloud Run deploy in one shot.

---

## API

```bash
# Register
curl -X POST https://mydragun.com/api/register \
  -H 'content-type: application/json' \
  -d '{"handle":"ember","passkey":"your-passkey","zip_code":"12345"}'

# Chat
curl -X POST https://mydragun.com/api/chat \
  -H 'content-type: application/json' \
  -d '{"user_id":"USER_ID","message":"I bought 3 shirts for $50"}'
```
