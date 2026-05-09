#!/bin/bash
cd "$(dirname "$0")"
git add dragun/app.py dragun/config.py dragun/static/index.html dragun/storage/firestore.py \
         dragun/services/agent.py dragun/services/parser.py deploy.sh
git commit -m "perf: Gemini context caching — upload tool schemas once, pay 25% per turn

- services/agent.py: split tool declarations (static) from implementations (per-user)
- _get_schema_cache(): uploads system instruction + tool schemas on first request, caches name globally
- run_agent(): uses cached_content when cache is available, falls back to inline schema if not
- ~75% reduction on the ~2K schema tokens sent every chat turn"
git push origin main
echo "✅ Pushed to GitHub."
