# LLM Council

![llmcouncil](header.jpg)

LLM Council is a local multi-model research app. Instead of asking one model for one answer, it sends your query to a council of models through OpenRouter, extracts structured claims, critiques those claims across models, triages disagreements, optionally verifies testable claims with sandboxed Python checks, and then synthesizes a final answer with a chairman model.

The current system keeps the original ranking-based pipeline as a fallback, but the primary path is now a structured, self-testing council flow.

## Pipeline

1. **Stage 1: Specialist responses**
    Each model answers the question and emits an evidence packet with claims and optional proposals.
2. **Stage 2: Claim critique**
    Models review anonymized specialist claims and identify agreements, disagreements, load-bearing points, and minority alerts.
3. **Fast Judge triage**
    A rule-based judge decides whether the council should synthesize immediately, verify claims, or request a second round.
4. **Verification**
    Testable claims run through AST-validated Python checks with bounded parallelism and isolated execution.
5. **Stage 3: Final synthesis**
    The chairman model produces the final answer using the specialist responses, critique, and any verification results.
6. **Optional second round**
    If key disagreements remain unresolved, the system can generate focused follow-up prompts and re-run the council.

## Features

- Side-by-side specialist responses in the UI
- Structured critique, judge, and verification panels
- Runtime council/chairman selection in the sidebar
- Streaming updates over SSE during execution
- Optional LangGraph-backed execution path
- Optional MCP server for tool-based integration
- Local conversation storage in `data/conversations/`

## Setup

### 1. Install dependencies

The project uses [uv](https://docs.astral.sh/uv/) for project management.

**Backend**
```bash
uv sync
```

**Frontend**
```bash
cd frontend
npm install
cd ..
```

### 2. Configure the API key

Create a `.env` file in the project root:

```bash
OPENROUTER_API_KEY=sk-or-v1-...
```

Get your API key at [openrouter.ai](https://openrouter.ai/). Make sure to purchase the credits you need, or sign up for automatic top up.

### 3. Configure models (optional)

Council members and the chairman model are configurable at runtime from the frontend sidebar or via the backend config endpoints. The active config is stored locally in `data/config.json`.

## Running the Application

**Option 1: Use the start script**
```bash
./start.sh
```

**Option 2: Run manually**

Terminal 1 (Backend):
```bash
uv run python -m backend.main
```

Terminal 2 (Frontend):
```bash
cd frontend
npm run dev
```

Then open http://localhost:5173 in your browser.

The backend listens on http://localhost:8001.

## API Surface

- `GET /api/models` returns available models and the current runtime config
- `GET /api/config` returns the current council config
- `POST /api/config` updates council members and chairman model
- `POST /api/conversations/{conversation_id}/message` runs the default council pipeline
- `POST /api/conversations/{conversation_id}/message/stream` streams stage updates over SSE
- `POST /api/conversations/{conversation_id}/message/langgraph` runs the optional LangGraph path

## Optional Integrations

### LangGraph

The project includes an optional LangGraph orchestration layer that mirrors the main structured pipeline without replacing the default execution path.

### MCP Server

Run the MCP server with:

```bash
uv run python -m backend.mcp_server
```

It exposes council execution and config management as MCP tools.

## Notes

- Conversations are stored locally in `data/conversations/`.
- Runtime configuration is stored locally in `data/config.json`.
- Structured metadata such as critique reports, judge decisions, and verification reports are returned by the API and shown in the UI, but only the main stage payloads are persisted to conversation JSON today.
- If the structured pipeline errors, the app falls back to the original ranking-based path instead of failing the request.

## Tech Stack

- **Backend:** FastAPI, Pydantic, async httpx, LangGraph, MCP
- **Frontend:** React + Vite, react-markdown for rendering
- **Storage:** JSON files in `data/conversations/`
- **Package Management:** uv for Python, npm for JavaScript
