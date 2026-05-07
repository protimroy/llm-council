---
name: llm-council-architecture
description: 'Use when working on LLM Council architecture, structured council stages, verification, retrieval, observability, runtime model config, deployment, or debugging pipeline behavior.'
argument-hint: 'Describe the LLM Council change, investigation, or debugging task.'
---

# LLM Council Architecture

## When To Use
- Changing backend council orchestration, Stage 1/2/3 behavior, Fast Judge, verification, retrieval, or observability.
- Debugging model configuration, OpenRouter calls, SSE streaming, metadata persistence, or frontend stage display.
- Planning deployment or environment configuration for this repository.

## Procedure
1. Read `.github/copilot-instructions.md` for current project-wide conventions.
2. Read `.claude/CLAUDE.md` for detailed architecture notes and historical implementation context.
3. Prefer existing patterns in `backend/council.py`, `backend/judge.py`, `backend/verification.py`, `backend/research.py`, and `frontend/src/components/`.
4. Validate backend changes with Python import/compile checks and frontend changes with `npm run lint` plus `npm run build` when applicable.

## Key Facts
- Backend defaults to port `8001`; frontend defaults to port `5173`.
- Runtime council selection is stored in `data/config.json`; deployment/default settings live in `.env`.
- Structured pipeline errors must fall back gracefully to the legacy ranking pipeline.
- Never log or echo `.env` secrets.
