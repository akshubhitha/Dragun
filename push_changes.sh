#!/bin/bash
cd "$(dirname "$0")"
git add \
  dragun/app.py \
  dragun/config.py \
  dragun/static/index.html \
  dragun/storage/firestore.py \
  dragun/services/agent.py \
  dragun/services/parser.py \
  deploy.sh \
  pyproject.toml \
  wipe_firestore.py \
  push_changes.sh \
  LICENSE
git commit -m "feat: Arize Phoenix tracing + Gemini 2.5 Flash + context caching

- app.py: _init_phoenix_tracing() — instruments all Gemini calls via OTel
- config.py: ARIZE_API_KEY env var
- pyproject.toml: arize-phoenix-otel + openinference-instrumentation-google-genai
- services/agent.py: context caching (~75% token cost reduction on schema prefix)
- config.py: default model gemini-2.5-flash (1.5 and 2.0 retired May 2026)
- deploy.sh: ARIZE_API_KEY env var, stable PASSKEY_SALT across deploys"
git push origin main
echo "✅ Pushed to GitHub."
