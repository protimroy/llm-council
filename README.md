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
    If key disagreements remain unresolved, the system builds a provider-backed web research briefing, generates focused follow-up prompts, and re-runs the council.

## Features

- Side-by-side specialist responses in the UI
- Structured critique, claim ledger, judge, and verification panels
- Searchable OpenRouter model catalog with runtime council/chairman selection
- Provider-returned reasoning artifacts and token usage shown per stage when available
- Streaming updates over SSE during execution
- Targeted research briefings for second-round follow-up, with Brave Search support and DuckDuckGo fallback
- Conversation export as Markdown/JSON plus repo-local research logs in `research_logs/`
- Research Session Mode with editable `plan.md`, appendable `research_log.md`, and council refinement actions
- Obsidian-style knowledge graph over saved research Markdown links and tags
- Upload or load a saved `plan.md`, research log, or research session as persistent context for the next council run
- Optional LangGraph-backed execution path
- Optional MCP server for tool-based integration
- Local conversation storage in `data/conversations/`, including structured critique/judge/verification metadata

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

Vite 7 requires Node.js `20.19+` or `22.12+`. Node `21.6.2` can build the frontend but fails to start the dev server because it lacks `crypto.hash`.

### 2. Configure environment variables

Copy `.env.example` to `.env`, then fill in your local values:

```bash
cp .env.example .env
```

At minimum, set `OPENROUTER_API_KEY`. The same file also controls API URLs, backend/frontend ports, CORS origins, default model selections, retrieval settings, and optional Phoenix tracing.

Get your OpenRouter API key at [openrouter.ai](https://openrouter.ai/). Make sure to purchase the credits you need, or sign up for automatic top up.

### 3. Configure models (optional)

Council members and the chairman model are configurable at runtime from the frontend sidebar or via the backend config endpoints. The active config is stored locally in `data/config.json`.

The sidebar pulls the full available model catalog from OpenRouter's `/api/v1/models` endpoint, caches it server-side, and lets you search/filter across providers. Models that advertise reasoning support are marked in the picker. The static list in `backend/config.py` is only a fallback if the catalog cannot be fetched.

The default council currently uses OpenRouter model IDs:

| Role | Model |
|------|-------|
| Specialist | `openai/gpt-5.5` |
| Specialist | `google/gemini-3-pro-preview` |
| Specialist | `anthropic/claude-opus-4.7` |
| Specialist | `x-ai/grok-4` |
| Chairman | `anthropic/claude-opus-4.7` |

Default selections come from `.env` through `backend/config.py`. Available sidebar choices are defined in `backend/config.py`; runtime selections are written to `data/config.json`.

Reasoning artifacts are requested through OpenRouter for models that advertise `include_reasoning` support:

```bash
OPENROUTER_MODELS_URL=https://openrouter.ai/api/v1/models
OPENROUTER_MODELS_CACHE_SECONDS=3600
OPENROUTER_INCLUDE_REASONING=true
```

Whether a model returns reasoning text or structured reasoning details depends on the provider/model route.

### 4. Research sessions, logs, and continuation context

The app can export the complete conversation as Markdown or JSON. It can also save a Markdown research log into `research_logs/`, a repo-local folder intended for normal Git review and commits.

```bash
RESEARCH_LOG_DIR=research_logs
```

From the chat workspace, you can upload a `plan.md`, research log, or JSON/TXT file. The loaded file becomes persistent context for the next council run in that conversation, so the council can continue from a prior plan without pasting the whole file into every prompt.

Research Session Mode creates folders under `research_logs/<session-slug>/` with an editable `plan.md`, an appendable `research_log.md`, and metadata in `session.json`. The workspace can load the whole session as conversation context, ask the council to critique it, ask the chairman to revise the plan, or extract verification tests.

The knowledge graph is built from explicit Markdown structure first: `[[wiki links]]`, relative Markdown links, and `#tags` across `research_logs/**/*.md`. This gives an Obsidian-like graph that is deterministic, cheap, Git-friendly, and easy to inspect. Embeddings and a vector database are useful later for semantic search, duplicate-note discovery, and suggested links, but they are not required for the first graph view.

The app deliberately does not run `git commit` for you. Saved logs appear as files in the repo so you can inspect the generated artifact, edit it, and commit it with your normal Git workflow.

### 5. Configure retrieval (optional)

Second-round research uses `RESEARCH_SEARCH_PROVIDER=auto` by default. In auto mode, Brave Search is used when `BRAVE_SEARCH_API_KEY` is present; otherwise the backend falls back to DuckDuckGo HTML search. Source-page excerpts are fetched best-effort and included in the follow-up prompt when available.

```bash
RESEARCH_SEARCH_PROVIDER=auto      # auto | brave | duckduckgo | disabled
BRAVE_SEARCH_API_KEY=your-brave-key
BRAVE_SEARCH_ENDPOINT=https://api.search.brave.com/res/v1/web/search
```

Set `RESEARCH_SEARCH_PROVIDER=disabled` to run second rounds from council context only.

### 6. Configure Arize Phoenix observability (optional)

Phoenix tracing is supported through OpenTelemetry and is disabled by default unless you explicitly enable it.

For Phoenix Cloud or a self-hosted collector, set:

```bash
PHOENIX_COLLECTOR_ENDPOINT=https://your-phoenix-endpoint
PHOENIX_API_KEY=your-phoenix-api-key
PHOENIX_PROJECT_NAME=llm-council
PHOENIX_TRACE_URL_TEMPLATE=https://your-phoenix-ui/projects/{project_name}/traces/{trace_id}
```

For a local Phoenix instance, you can point at your local collector and enable tracing explicitly:

```bash
PHOENIX_ENABLED=true
PHOENIX_COLLECTOR_ENDPOINT=http://localhost:6006
PHOENIX_PROJECT_NAME=llm-council
```

`PHOENIX_TRACE_URL_TEMPLATE` is optional. If you provide it, the chat UI will render an "Open Phoenix Trace" link for each assistant run. Supported placeholders are `{project_name}`, `{trace_id}`, and `{span_id}`.

With Phoenix configured, the backend will emit traces for council requests, stage orchestration, OpenRouter prompt/query calls, sandboxed verification tool execution, and MCP tool invocations. The current trace ID is also surfaced back through API metadata and the chat UI.

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

If your local Node version cannot run the Vite dev server, build and serve the static bundle instead:

```bash
cd frontend
npm run build
cd dist
python -m http.server 5173 --bind 127.0.0.1
```

## API Surface

- `GET /api/models` returns the OpenRouter model catalog and the current runtime config
- `POST /api/models/refresh` force-refreshes the OpenRouter model catalog cache
- `GET /api/config` returns the current council config
- `POST /api/config` updates council members and chairman model
- `GET /api/conversations/{conversation_id}/export?format=markdown|json` exports the complete conversation
- `POST /api/conversations/{conversation_id}/research-log` saves a Markdown research log into `research_logs/`
- `GET /api/research-logs` lists saved repo-local research logs
- `GET /api/research-sessions` lists repo-local research sessions
- `POST /api/research-sessions` creates a session folder with `plan.md` and `research_log.md`
- `GET /api/research-sessions/{session_id}` reads a research session and its Markdown files
- `POST /api/research-sessions/{session_id}/files` creates or replaces a session Markdown file
- `POST /api/research-sessions/{session_id}/log` appends a dated entry to `research_log.md`
- `GET /api/research-graph` builds a graph from research Markdown links and tags
- `POST /api/conversations/{conversation_id}/research-context` loads uploaded research context
- `POST /api/conversations/{conversation_id}/research-context/from-log` loads a saved research log as context
- `POST /api/conversations/{conversation_id}/research-context/from-session` loads a research session as context
- `DELETE /api/conversations/{conversation_id}/research-context` clears loaded context
- `POST /api/conversations/{conversation_id}/message` runs the default council pipeline
- `POST /api/conversations/{conversation_id}/message/stream` streams stage updates over SSE
- `POST /api/conversations/{conversation_id}/message/langgraph` runs the optional LangGraph path

## How This Differs From Karpathy's LLM Council

Karpathy's LLM council idea is usually understood as a lightweight multi-model pattern: ask several models the same question, compare their answers, and have a final model or human synthesize the result. That is a useful baseline because it gets diversity and cross-checking with very little machinery.

LLM Council keeps that spirit, but turns it into a research and development workflow:

- It extracts structured claims and proposals instead of treating each model answer as one indivisible blob.
- It critiques claims against other claims, so disagreement is tracked at the load-bearing assertion level.
- It uses a deterministic Fast Judge to decide whether to synthesize, verify, or run a second round.
- It can run sandboxed Python checks for falsifiable claims instead of relying only on model debate.
- It can pull targeted retrieval briefings for unresolved issues and feed those into a second round.
- It persists the full deliberation, metadata, reasoning artifacts, traces, and research logs for later review.
- It supports dynamic model selection from OpenRouter instead of a fixed council roster.

In short: the Karpathy-style council is a prompt pattern; this project is a local research system around that pattern, with provenance, persistence, verification hooks, and continuation from saved plans.

## Optional Integrations

### LangGraph

The project includes an optional LangGraph orchestration layer that mirrors the main structured pipeline without replacing the default execution path.

### MCP Server

Run the MCP server with:

```bash
uv run python -m backend.mcp_server
```

It exposes council execution and config management as MCP tools.

## Deployment

For a VPC deployment without Docker, use a VM plus systemd services. See [docs/deploy-vpc-systemd.md](docs/deploy-vpc-systemd.md) for the recommended setup, service templates, and reverse proxy notes.

## Notes

- Conversations are stored locally in `data/conversations/`.
- Repo-local research logs are stored in `research_logs/` so they can be reviewed and committed normally.
- Runtime configuration is stored locally in `data/config.json`.
- Deployment and default configuration are stored in `.env`; keep `.env` private and use `.env.example` as the shareable template.
- Agent customization files live in default folders: `.claude/CLAUDE.md`, `.github/copilot-instructions.md`, `.github/agents/`, and `.github/skills/`.
- Structured metadata such as critique reports, judge decisions, verification reports, final decisions, traces, and second-round research briefings are persisted with assistant messages.
- If the structured pipeline errors, the app falls back to the original ranking-based path instead of failing the request.

## Troubleshooting

- `401 Unauthorized` from OpenRouter means `OPENROUTER_API_KEY` is missing, invalid, revoked, or not loaded by the running backend. Create/update `.env` with `OPENROUTER_API_KEY=sk-or-v1-...`, then restart the backend.
- `402 Payment Required` from OpenRouter means the key is valid, but the account/key needs credits, billing, or access for the selected model route.
- If model calls still fail after updating `.env`, verify the key in OpenRouter and make sure the backend was started from the project root so `python-dotenv` can load the file.

## Tech Stack

- **Backend:** FastAPI, Pydantic, async httpx, LangGraph, MCP
- **Frontend:** React + Vite, react-markdown for rendering
- **Storage:** JSON files in `data/conversations/`
- **Package Management:** uv for Python, npm for JavaScript
