# Archived — "Simple/MVP" parallel stack (VAL-167, 2026-06-01)

This directory holds the abandoned single-file MVP track, archived during the
2026-06-01 foundations audit. **It is not the shipped product** and is kept only
as a decision trail.

## Why it was archived
- `simple_api.py` is a 3-endpoint single-file FastAPI server (`title="Valinor SaaS - Simple MVP"`).
- Its only runner, `valinor_runner.py`, imports `valinor.run.run_full_analysis` and
  `valinor.config.create_client_config` — **symbols that do not exist** in the real
  `core/valinor` package — so it always falls back to `run_simulated_analysis()` and
  returns hardcoded mock numbers (e.g. revenue `$2,456,789`).
- Nothing in CI, the canonical `docker-compose.yml`, the `Makefile`, or `CLAUDE.md`
  references any of these files.

## The real product
`docker compose up -d` → `uvicorn api.main:app` + `celery -A worker.celery_app` + the
Next.js app in `web/`. See `README.md`, `docs/PROJECT_STATE.md`, and `INFRASTRUCTURE.md`.

## Contents
- `simple_api.py`, `valinor_runner.py`, `serve_web.py` — dead MVP code
- `README_SIMPLE.md`, `SIMPLIFICATION_REPORT.md`, `TESTING_INSTRUCTIONS.md` — docs for the dead track
- `start_simple.sh`, `start_mvp.sh`, `requirements_simple.txt` — launchers/deps
- `Dockerfile.simple`, `docker-compose.simple.yml` — simple-stack images
- `docker-compose.dev.yml`, `Dockerfile` — orphaned dev stack (referenced a non-existent `demo/` dir and the wrong celery entrypoint)
