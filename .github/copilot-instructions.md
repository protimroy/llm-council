# LLM Council Project Guidelines

## Architecture
- LLM Council is a structured multi-model research app: Stage 1 evidence packets, Stage 2 claim critique, Fast Judge triage, optional verification, optional second round, then Stage 3 synthesis.
- Preserve the fallback path to the original ranking-based pipeline when the structured path errors.
- Keep backend imports relative, for example `from .config import ...`.
- Detailed historical notes live in `.claude/CLAUDE.md`.

## Backend
- Run backend commands from the repository root with `uv run python -m backend.main`.
- Backend settings come from `.env` through `backend/config.py`; do not hard-code ports, model defaults, API URLs, CORS origins, or data paths.
- `data/config.json` is runtime UI state for council/chairman selections and is intentionally gitignored.
- Backend default port is `8001`.

## Frontend
- Frontend lives in `frontend/` and uses React + Vite.
- `frontend/src/api.js` reads `VITE_API_BASE`, with `http://localhost:8001` as the local fallback.
- Vite env loading is configured to read the repository-root `.env`.
- Frontend default port is `5173`.

## Verification
- For Python changes, run import/compile checks through the configured virtual environment or `uv run`.
- For frontend changes, run `npm run lint` and `npm run build` from `frontend/`.
- Avoid printing secrets from `.env` or API responses.
