# CLAUDE.md - Technical Notes for LLM Council

This file contains technical details, architectural decisions, and important implementation notes for future development sessions.

## Project Overview

LLM Council is a **Self-Testing Agentic Research System** where multiple LLMs collaboratively answer user questions through structured deliberation. The system generates evidence-backed claims, runs claim-level critique, triages disagreements via a Fast Judge, verifies falsifiable claims via executable Python tests, and synthesizes a final answer — falling back to the original prose-ranking pipeline on any error.

## Implementation Status

### ✅ Implemented
| Phase | Component | File(s) |
|-------|-----------|---------|
| 1 | Pydantic data contracts (21 types) | `backend/models.py` |
| 2 | Stage 1 structured output (evidence packets) | `backend/prompts.py`, `backend/parsing.py`, `backend/council.py` |
| 3 | Stage 2 claim-level critique | `backend/council.py` (stage2_critique_claims, _merge_critique_reports) |
| 4 | Fast Judge triage | `backend/judge.py` |
| 5 | Verification runner | `backend/verification.py` (AST validation, bounded parallelism, namespace sandboxing) |
| 6 | Post-verification judge | `backend/judge.py` |
| 7 | Enriched Stage 3 synthesis | `backend/council.py` (_build_enriched_prompt) |
| 8 | Full pipeline wiring + SSE streaming | `backend/council.py` (run_full_council), `backend/main.py` |
| 9 | Recursive second-round loop | `backend/council.py` (run_second_round) |
| 10 | Frontend display for structured stages | `frontend/src/components/StageCritique.jsx`, `StageJudge.jsx`, `StageVerification.jsx` |
| 11 | Configurable council via UI | `backend/config.py`, `backend/main.py`, `frontend/src/components/Sidebar.jsx` |
| 12 | Optional LangGraph/MCP integration | `backend/langgraph_pipeline.py`, `backend/mcp_server.py` |

### Residual Hardening
| Priority | Task | Notes |
|----------|------|-------|
| Medium | Stronger container isolation | Current verification uses `unshare` namespaces and resource limits; Docker/seccomp would be stricter |
| Low | Persist metadata to storage | Judge/verification metadata is still API-only and not written into conversation JSON |
| Low | Frontend engine selector | LangGraph execution is exposed through backend/MCP, but not selectable in the UI |

## Architecture

### Backend Structure (`backend/`)

**`models.py`** — Pydantic Data Contracts
- 8 enums: `ClaimType`, `EvidenceType`, `SeverityLevel`, `RecommendedAction`, `TriageDecision`, `VerificationStatus`, `VerificationTargetType`, `PostVerificationAction`, `FinalDecisionType`
- 11 models: `Claim`, `Proposal`, `EvidencePacket`, `Agreement`, `Disagreement`, `LoadBearingCandidate`, `SelectedHypothesis`, `MinorityAlert`, `CritiqueReport`, `FastJudgeDecision`, `VerificationTarget`, `VerificationResult`, `VerificationReport`, `FinalDecision`
- Key: `EvidencePacket` has `parse_error` field for fallback; all list fields use `default_factory=list`

**`prompts.py`** — Prompt Templates
- `STAGE1_SPECIALIST_PROMPT`: System message instructing models to write prose then `---EVIDENCE_PACKET---` then JSON with claims/proposals schema
- `STAGE2_CRITIQUE_PROMPT`: Template with `{user_query}` and `{claims_text}` placeholders; requires `---CRITIQUE_REPORT---` delimiter then JSON

**`parsing.py`** — Delimiter-Based Structured Output Parser
- `parse_evidence_packet(raw_text, model_name) -> tuple[str, EvidencePacket]`: Always returns (prose, packet); on failure returns fallback EvidencePacket with `parse_error` populated
- `parse_critique_report(raw_text) -> tuple[str, CritiqueReport | None, str | None]`: Returns (prose, report_or_None, error_or_None)
- `_normalize_enum(value, enum_class, default)`: Normalizes string values to valid enum members

**`judge.py`** — Fast Judge Triage
- `fast_judge_triage(critique_report) -> FastJudgeDecision`: Rule-based heuristic — load-bearing + weak evidence → escalate_for_verification; high-severity + high-impact → request_second_round; otherwise → synthesize_now
- `select_verification_targets(judge_decision, critique_report, stage1_results) -> list[VerificationTarget]`: Looks up claims by ID in evidence packets; claims with falsifiable_hypothesis + test_logic → python_check; capped at 3 targets
- `post_verification_judge(critique_report, judge_decision, verification_report) -> FinalDecision`: Classifies claims as resolved/rejected/unresolved; determines synthesize/second_round/unresolved decision

**`verification.py`** — Safe Python Code Execution
- `_validate_code(code) -> tuple[bool, str]`: AST-based safety check with string fallback for syntax errors
- `_run_python_snippet(code, timeout) -> tuple[stdout, stderr, returncode, timed_out, sandbox_strategy]`: Runs code through a restricted wrapper under `unshare` when available
- `run_single_verification(target) -> VerificationResult`: Maps target type and execution result to status and records sandbox notes
- `run_verification(targets) -> VerificationReport`: Executes targets in bounded parallelism via `asyncio.gather()` + semaphore

**`council.py`** — Core Pipeline Logic
- `stage1_collect_responses()`: Sends system prompt (STAGE1_SPECIALIST_PROMPT) + user query, calls parse_evidence_packet, returns `{model, response (prose), evidence_packet (dict)}`
- `stage2_critique_claims()`: Anonymizes claims as "Specialist A/B/C", sends STAGE2_CRITIQUE_PROMPT, parses responses, merges individual reports, returns backward-compatible stage2 results + label_to_model + merged CritiqueReport
- `_merge_critique_reports()`: Union agreements (dedup by claim_ids overlap), merge disagreements (take highest severity), union load-bearing/hypotheses/alerts
- `aggregate_from_critique()`: Synthetic aggregate_rankings from critique for frontend compatibility
- `stage3_synthesize_final()`: Accepts optional critique_report, final_decision, verification_report; uses enriched prompt with structured data when available, falls back to original format
- `_build_enriched_prompt()`: Builds chairman prompt with agreements, disagreements, minority alerts, verification results, and decision context
- `run_full_council()`: New pipeline: stage1 → stage2_critique → fast_judge → verification (if escalated) → post_verification_judge → stage3 (enriched). Wrapped in try/except with fallback to `_run_original_pipeline()`
- `_run_original_pipeline()`: Fallback using original stage2_collect_rankings + old stage3
- `run_second_round()`: Generates targeted follow-up prompts from unresolved claims / next actions, re-runs specialists, and re-enters the structured pipeline with bounded recursion
- **Preserved legacy functions**: `stage2_collect_rankings()`, `parse_ranking_from_text()`, `calculate_aggregate_rankings()`

**`config.py`**
- Runtime config stored in `data/config.json` with `load_config()`, `save_config()`, `get_council_models()`, `get_chairman_model()`
- `AVAILABLE_MODELS` provides the selection list used by the frontend settings panel
- Uses environment variable `OPENROUTER_API_KEY` from `.env`
- Backend runs on **port 8001** (NOT 8000 — user had another app on 8000)

**`langgraph_pipeline.py`**
- Optional LangGraph state-machine orchestration that mirrors the structured council pipeline
- `run_full_council_langgraph()` returns the same output contract as `run_full_council()` and falls back on graph failure

**`mcp_server.py`**
- Optional MCP server exposing council execution and config management as tools
- Run via `uv run python -m backend.mcp_server`

**`openrouter.py`**
- `query_model()`: Single async model query
- `query_models_parallel()`: Parallel queries using `asyncio.gather()`
- Returns dict with 'content' and optional 'reasoning_details'
- Graceful degradation: returns None on failure, continues with successful responses

**`storage.py`**
- JSON-based conversation storage in `data/conversations/`
- Each conversation: `{id, created_at, messages[]}`
- Assistant messages contain: `{role, stage1, stage2, stage3}`
- Note: metadata (label_to_model, aggregate_rankings, critique_report, verification_report, etc.) is NOT persisted to storage, only returned via API

**`main.py`**
- FastAPI app with CORS enabled for localhost:5173 and localhost:3000
- POST `/api/conversations/{id}/message` — non-streaming endpoint, uses `run_full_council()` which handles fallback internally
- POST `/api/conversations/{id}/message/langgraph` — optional non-streaming endpoint that executes through LangGraph
- POST `/api/conversations/{id}/message/stream` — SSE streaming endpoint with new events: `fast_judge_start/complete`, `verification_start/complete`, `post_judge_complete` between stage2 and stage3; try/except fallback to original pipeline on error
- GET `/api/models`, GET `/api/config`, POST `/api/config` — model listing and runtime council configuration endpoints
- Metadata includes: label_to_model mapping, aggregate_rankings, critique_report, judge_decision, verification_report, final_decision

### Frontend Structure (`frontend/src/`)

**`App.jsx`**
- Main orchestration: manages conversations list and current conversation
- Handles message sending and metadata storage
- Important: metadata is stored in the UI state for display but not persisted to backend JSON

**`components/ChatInterface.jsx`**
- Multiline textarea (3 rows, resizable)
- Enter to send, Shift+Enter for new line
- User messages wrapped in markdown-content class for padding
- Renders structured critique, judge decisions, verification status, and second-round state between Stage 2 and Stage 3

**`components/Stage1.jsx`**
- Tab view of individual model responses
- ReactMarkdown rendering with markdown-content wrapper

**`components/Stage2.jsx`**
- **Critical Feature**: Tab view showing RAW evaluation text from each model
- De-anonymization happens CLIENT-SIDE for display (models receive anonymous labels)
- Shows "Extracted Ranking" below each evaluation so users can validate parsing
- Aggregate rankings shown with average position and vote count
- Explanatory text clarifies that boldface model names are for readability only
- **Note**: Critique prose still renders through the Stage 2 tabs for backward compatibility.

**`components/StageCritique.jsx`**
- Summary panel for agreements, disagreements, load-bearing points, and minority alerts

**`components/StageJudge.jsx`**
- Displays Fast Judge triage and post-verification final decision state

**`components/StageVerification.jsx`**
- Displays verification results, statuses, execution times, and counts

**`components/Sidebar.jsx`**
- Includes runtime settings for selecting council members and chairman model

**`components/Stage3.jsx`**
- Final synthesized answer from chairman
- Green-tinted background (#f0fff0) to highlight conclusion

**Styling (`*.css`)**
- Light mode theme (not dark mode)
- Primary color: #4a90e2 (blue)
- Global markdown styling in `index.css` with `.markdown-content` class
- 12px padding on all markdown content to prevent cluttered appearance

## Key Design Decisions

### Delimiter-Based Structured Output
Models write prose first, then `---EVIDENCE_PACKET---` (or `---CRITIQUE_REPORT---`), then JSON. This avoids the complexity of function calling while keeping prose readable. The parser always returns a tuple — on failure, the EvidencePacket has `parse_error` populated and empty claims, so the pipeline never crashes.

### Backward Compatibility Strategy
The new pipeline wraps in try/except and falls back to `_run_original_pipeline()` on any error. Stage 2 critique results maintain the same dict shape as ranking results (`ranking` key with prose, `parsed_ranking` as empty list). The frontend's `deAnonymizeText` uses generic regex that works with both "Response A" and "Specialist A" prefixes.

### Stage 2 Claim-Level Critique
Instead of ranking whole responses, Stage 2 now identifies specific agreements, disagreements, load-bearing claims, and minority alerts. The `_merge_critique_reports()` function unions agreements (dedup by claim_ids overlap), takes highest-severity disagreements, and unions load-bearing/hypotheses/alerts.

### Fast Judge Triage
Rule-based heuristic (not LLM-based) for speed and determinism:
- Load-bearing claim + weak evidence → `escalate_for_verification`
- High-severity + high-impact disagreement → `request_second_round`
- Otherwise → `synthesize_now`

### Verification Safety
- AST-based code validation with string fallback for syntax errors
- Verification subprocess runs through a restricted wrapper with safe builtins/import allowlist
- Linux namespace sandboxing via `unshare` when available, with stripped environment and hard resource limits
- Bounded parallel execution via `asyncio.gather()` + semaphore
- **Residual limitation**: container-level isolation (Docker/seccomp) would still be stricter than namespace-only sandboxing

### De-anonymization Strategy
- Stage 2 critique: Models receive "Specialist A", "Specialist B", etc.
- Backend creates mapping: `{"Specialist A": "openai/gpt-5.1", ...}`
- Frontend displays model names in **bold** for readability
- Users see explanation that original evaluation used anonymous labels
- This prevents bias while maintaining transparency

### Error Handling Philosophy
- Continue with successful responses if some models fail (graceful degradation)
- Never fail the entire request due to single model failure
- New pipeline falls back to original pipeline on any error
- Log errors but don't expose to user unless all models fail

### UI/UX Transparency
- All raw outputs are inspectable via tabs
- Parsed data shown below raw text for validation
- Users can verify system's interpretation of model outputs
- This builds trust and allows debugging of edge cases

## Important Implementation Details

### Relative Imports
All backend modules use relative imports (e.g., `from .config import ...`) not absolute imports. This is critical for Python's module system to work correctly when running as `python -m backend.main`.

### Port Configuration
- Backend: 8001 (changed from 8000 to avoid conflict)
- Frontend: 5173 (Vite default)
- Update both `backend/main.py` and `frontend/src/api.js` if changing

### Markdown Rendering
All ReactMarkdown components must be wrapped in `<div className="markdown-content">` for proper spacing. This class is defined globally in `index.css`.

### Model Configuration
Runtime model selection is stored in `data/config.json`. Council members and chairman can be changed through the frontend settings panel or config endpoints.

### SSE Streaming Events
The streaming endpoint emits these events in order:
1. `stage1_start` / `stage1_complete`
2. `stage2_start` / `stage2_complete`
3. `fast_judge_start` / `fast_judge_complete`
4. `verification_start` / `verification_complete` (only if escalated)
5. `post_judge_complete`
6. `stage3_start` / `stage3_complete`
7. `metadata` (label_to_model, aggregate_rankings, etc.)

## Common Gotchas

1. **Module Import Errors**: Always run backend as `python -m backend.main` from project root, not from backend directory
2. **CORS Issues**: Frontend must match allowed origins in `main.py` CORS middleware
3. **Ranking Parse Failures**: If models don't follow format, fallback regex extracts any "Response X" patterns in order
4. **Missing Metadata**: Metadata is ephemeral (not persisted), only available in API responses
5. **Evidence Packet Parse Failures**: Parser always returns a valid EvidencePacket — check `parse_error` field to detect failures
6. **Verification Isolation**: Current sandboxing uses `unshare` + resource limits when available; if you need stricter isolation, move to Docker/seccomp
7. **Metadata Persistence**: critique_report, judge decisions, and verification reports are returned by the API and rendered in the frontend, but are still not written into stored conversation JSON

## Testing Notes

Use `test_openrouter.py` to verify API connectivity and test different model identifiers before adding to council. The script tests both streaming and non-streaming modes.

Verified tests (all passing as of implementation):
- All module imports: models, parsing, judge, verification, council, main app
- Server boots cleanly on port 8001
- Code validator: safe code passes; `import os`, `exec(`, `open write`, `import socket`, empty code all rejected
- Fast Judge: None/empty critique → synthesize_now; high-severity + load-bearing + weak evidence → escalate_for_verification
- Parser: valid JSON with delimiter → parsed; no delimiter → fallback with parse_error; broken JSON → fallback with parse_error

## Data Flow Summary

```
User Query
    ↓
Stage 1: Parallel queries with STAGE1_SPECIALIST_PROMPT
    → parse_evidence_packet() → [{model, response (prose), evidence_packet}]
    ↓
Stage 2: Anonymize claims as "Specialist A/B/C"
    → stage2_critique_claims() → parse_critique_report() → _merge_critique_reports()
    → CritiqueReport (agreements, disagreements, load_bearing, minority_alerts)
    ↓
Fast Judge: fast_judge_triage(critique_report)
    → FastJudgeDecision (synthesize_now | escalate_for_verification | request_second_round)
    ↓
[If escalated] Verification: select_verification_targets() → run_verification()
    → VerificationReport (results per claim, recommended_next_step)
    ↓
[If escalated] Post-Verification Judge: post_verification_judge()
    → FinalDecision (synthesize | second_round | unresolved)
    ↓
Stage 3: stage3_synthesize_final() with enriched prompt (or original fallback)
    → Chairman synthesis
    ↓
Return: {stage1, stage2, stage3, metadata}
    ↓
Frontend: Display with tabs + validation UI
```

On any error in the new pipeline, falls back to `_run_original_pipeline()` which uses the original Stage 2 ranking + Stage 3 synthesis flow.
