"""FastAPI backend for LLM Council."""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import uuid
import json
import asyncio

from . import storage
from .config import BACKEND_HOST, BACKEND_PORT, CORS_ORIGINS, load_config, save_config, AVAILABLE_MODELS
from .council import (
    run_full_council, generate_conversation_title,
    stage1_collect_responses, stage2_collect_rankings, stage2_critique_claims,
    stage3_synthesize_final, calculate_aggregate_rankings, aggregate_from_critique,
    run_second_round,
)
from .langgraph_pipeline import run_full_council_langgraph
from .models import FinalDecisionType
from .observability import get_current_trace_payload, get_tracer, mark_span_error, mark_span_ok, using_trace_context
from .openrouter import fetch_openrouter_models
from .judge import fast_judge_triage, select_verification_targets, post_verification_judge
from .verification import run_verification

app = FastAPI(title="LLM Council API")
tracer = get_tracer(__name__)

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CreateConversationRequest(BaseModel):
    """Request to create a new conversation."""
    pass


class SendMessageRequest(BaseModel):
    """Request to send a message in a conversation."""
    content: str


class UpdateConfigRequest(BaseModel):
    """Request to update council configuration."""
    council_models: List[str]
    chairman_model: str


class ResearchContextRequest(BaseModel):
    """Request to attach uploaded research context to a conversation."""
    filename: str
    content: str


class ResearchLogLoadRequest(BaseModel):
    """Request to attach a saved repo research log to a conversation."""
    filename: str


class ConversationMetadata(BaseModel):
    """Conversation metadata for list view."""
    id: str
    created_at: str
    title: str
    message_count: int


class Conversation(BaseModel):
    """Full conversation with all messages."""
    id: str
    created_at: str
    title: str
    research_context: Optional[Dict[str, Any]] = None
    messages: List[Dict[str, Any]]


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "service": "LLM Council API"}


@app.get("/api/models")
async def list_models():
    """List available models and current council configuration."""
    current_config = load_config()
    catalog = await fetch_openrouter_models()
    return {
        "available_models": catalog.get("available_models") or AVAILABLE_MODELS,
        "model_source": catalog.get("source"),
        "model_catalog_error": catalog.get("error"),
        "model_catalog_fetched_at": catalog.get("fetched_at"),
        "current_config": current_config,
    }


@app.post("/api/models/refresh")
async def refresh_models():
    """Force-refresh the OpenRouter model catalog."""
    catalog = await fetch_openrouter_models(force_refresh=True)
    return catalog


@app.get("/api/config")
async def get_config():
    """Get the current council configuration."""
    return load_config()


@app.post("/api/config")
async def update_config(request: UpdateConfigRequest):
    """Update the council configuration."""
    if not request.council_models:
        raise HTTPException(status_code=400, detail="At least one council model is required")

    if request.chairman_model not in request.council_models:
        # Allow chairman to be outside the council, but warn if needed in future.
        pass

    config = save_config(request.council_models, request.chairman_model)
    return config


@app.get("/api/conversations", response_model=List[ConversationMetadata])
async def list_conversations():
    """List all conversations (metadata only)."""
    return storage.list_conversations()


@app.post("/api/conversations", response_model=Conversation)
async def create_conversation(request: CreateConversationRequest):
    """Create a new conversation."""
    conversation_id = str(uuid.uuid4())
    conversation = storage.create_conversation(conversation_id)
    return conversation


@app.get("/api/conversations/{conversation_id}", response_model=Conversation)
async def get_conversation(conversation_id: str):
    """Get a specific conversation with all its messages."""
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@app.get("/api/conversations/{conversation_id}/export")
async def export_conversation(conversation_id: str, format: str = "markdown"):
    """Export a complete conversation as Markdown or JSON text."""
    if format not in {"markdown", "json"}:
        raise HTTPException(status_code=400, detail="format must be markdown or json")
    try:
        return storage.export_conversation(conversation_id, format)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/conversations/{conversation_id}/research-log")
async def save_research_log(conversation_id: str):
    """Save a conversation markdown research log into the repo-local log folder."""
    try:
        return storage.save_research_log(conversation_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/research-logs")
async def list_research_logs():
    """List saved repo-local research logs."""
    return {"logs": storage.list_research_logs()}


@app.post("/api/conversations/{conversation_id}/research-context")
async def set_research_context(conversation_id: str, request: ResearchContextRequest):
    """Attach uploaded research context to a conversation."""
    try:
        return storage.set_research_context(conversation_id, request.filename, request.content)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/conversations/{conversation_id}/research-context/from-log")
async def set_research_context_from_log(conversation_id: str, request: ResearchLogLoadRequest):
    """Attach a saved repo-local research log to a conversation."""
    try:
        log = storage.read_research_log(request.filename)
        return storage.set_research_context(conversation_id, log["filename"], log["content"])
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/conversations/{conversation_id}/research-context")
async def clear_research_context(conversation_id: str):
    """Clear loaded research context from a conversation."""
    try:
        return storage.clear_research_context(conversation_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/conversations/{conversation_id}/message")
async def send_message(conversation_id: str, request: SendMessageRequest):
    """
    Send a message and run the 3-stage council process.
    Returns the complete response with all stages.
    """
    with tracer.start_as_current_span(
        "api.send_message",
        openinference_span_kind="agent",
    ) as span:
        span.set_input({
            "conversation_id": conversation_id,
            "content_characters": len(request.content),
            "stream": False,
        })
        span.set_attribute("conversation.id", conversation_id)

        with using_trace_context(
            conversation_id=conversation_id,
            request_mode="sync",
            request_transport="http",
            council_engine="default",
        ):
            try:
                # Check if conversation exists
                conversation = storage.get_conversation(conversation_id)
                if conversation is None:
                    raise HTTPException(status_code=404, detail="Conversation not found")

                # Check if this is the first message
                is_first_message = len(conversation["messages"]) == 0

                council_query = storage.build_contextual_user_query(conversation, request.content)

                # Add user message
                storage.add_user_message(conversation_id, request.content)

                # If this is the first message, generate a title
                if is_first_message:
                    title = await generate_conversation_title(request.content)
                    storage.update_conversation_title(conversation_id, title)

                # Run the 3-stage council process
                stage1_results, stage2_results, stage3_result, metadata = await run_full_council(
                    council_query
                )

                trace_payload = get_current_trace_payload()

                # Add assistant message with all stages
                storage.add_assistant_message(
                    conversation_id,
                    stage1_results,
                    stage2_results,
                    stage3_result,
                    metadata=metadata,
                    trace=trace_payload,
                )

                result = {
                    "stage1": stage1_results,
                    "stage2": stage2_results,
                    "stage3": stage3_result,
                    "metadata": metadata,
                    "trace": trace_payload,
                }
                span.set_output({
                    "stage1_count": len(stage1_results),
                    "stage2_count": len(stage2_results),
                    "stage3_model": stage3_result.get("model"),
                    "stage3_response_characters": len(stage3_result.get("response", "")),
                    "metadata_keys": list(metadata.keys()) if isinstance(metadata, dict) else [],
                    "trace": trace_payload,
                })
                mark_span_ok(span)
                return result
            except Exception as exc:
                mark_span_error(span, exc)
                raise


@app.post("/api/conversations/{conversation_id}/message/langgraph")
async def send_message_langgraph(conversation_id: str, request: SendMessageRequest):
    """Send a message and run the LangGraph-backed council process."""
    with tracer.start_as_current_span(
        "api.send_message_langgraph",
        openinference_span_kind="agent",
    ) as span:
        span.set_input({
            "conversation_id": conversation_id,
            "content_characters": len(request.content),
            "engine": "langgraph",
        })
        span.set_attribute("conversation.id", conversation_id)
        span.set_attribute("council.engine", "langgraph")

        with using_trace_context(
            conversation_id=conversation_id,
            request_mode="sync",
            request_transport="http",
            council_engine="langgraph",
        ):
            try:
                conversation = storage.get_conversation(conversation_id)
                if conversation is None:
                    raise HTTPException(status_code=404, detail="Conversation not found")

                is_first_message = len(conversation["messages"]) == 0
                council_query = storage.build_contextual_user_query(conversation, request.content)
                storage.add_user_message(conversation_id, request.content)

                if is_first_message:
                    title = await generate_conversation_title(request.content)
                    storage.update_conversation_title(conversation_id, title)

                stage1_results, stage2_results, stage3_result, metadata = await run_full_council_langgraph(
                    council_query
                )

                trace_payload = get_current_trace_payload()

                storage.add_assistant_message(
                    conversation_id,
                    stage1_results,
                    stage2_results,
                    stage3_result,
                    metadata=metadata,
                    trace=trace_payload,
                )

                result = {
                    "stage1": stage1_results,
                    "stage2": stage2_results,
                    "stage3": stage3_result,
                    "metadata": metadata,
                    "trace": trace_payload,
                }
                span.set_output({
                    "stage1_count": len(stage1_results),
                    "stage2_count": len(stage2_results),
                    "stage3_model": stage3_result.get("model"),
                    "stage3_response_characters": len(stage3_result.get("response", "")),
                    "metadata_keys": list(metadata.keys()) if isinstance(metadata, dict) else [],
                    "trace": trace_payload,
                })
                mark_span_ok(span)
                return result
            except Exception as exc:
                mark_span_error(span, exc)
                raise


@app.post("/api/conversations/{conversation_id}/message/stream")
async def send_message_stream(conversation_id: str, request: SendMessageRequest):
    """
    Send a message and stream the 3-stage council process.
    Returns Server-Sent Events as each stage completes.
    """
    # Check if conversation exists
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check if this is the first message
    is_first_message = len(conversation["messages"]) == 0

    async def event_generator():
        with tracer.start_as_current_span(
            "api.send_message_stream",
            openinference_span_kind="agent",
        ) as span:
            span.set_input({
                "conversation_id": conversation_id,
                "content_characters": len(request.content),
                "stream": True,
            })
            span.set_attribute("conversation.id", conversation_id)

            with using_trace_context(
                conversation_id=conversation_id,
                request_mode="stream",
                request_transport="sse",
                council_engine="default",
            ):
                try:
                    trace_payload = get_current_trace_payload()
                    yield f"data: {json.dumps({'type': 'trace_context', 'data': trace_payload})}\n\n"

                # Add user message
                    storage.add_user_message(conversation_id, request.content)

                    council_query = storage.build_contextual_user_query(conversation, request.content)

                    # Start title generation in parallel (don't await yet)
                    title_task = None
                    if is_first_message:
                        title_task = asyncio.create_task(generate_conversation_title(request.content))

                    # Stage 1: Collect responses (with evidence packets)
                    yield f"data: {json.dumps({'type': 'stage1_start'})}\n\n"
                    stage1_results = await stage1_collect_responses(council_query)
                    yield f"data: {json.dumps({'type': 'stage1_complete', 'data': stage1_results})}\n\n"

                    if not stage1_results:
                        yield f"data: {json.dumps({'type': 'error', 'message': 'All models failed to respond. Please try again.'})}\n\n"
                        return

                    message_metadata = None

                    # Try the new structured pipeline
                    try:
                    # Stage 2: Claim-level critique
                        yield f"data: {json.dumps({'type': 'stage2_start'})}\n\n"
                        stage2_results, label_to_model, critique_report = await stage2_critique_claims(council_query, stage1_results)
                        aggregate_rankings = aggregate_from_critique(critique_report, label_to_model)
                        stage2_metadata = {
                            'label_to_model': label_to_model,
                            'aggregate_rankings': aggregate_rankings,
                            'critique_report': critique_report.model_dump() if critique_report else None,
                            'trace': trace_payload,
                        }
                        yield f"data: {json.dumps({'type': 'stage2_complete', 'data': stage2_results, 'metadata': stage2_metadata})}\n\n"

                    # Fast Judge: Triage decision
                        yield f"data: {json.dumps({'type': 'fast_judge_start'})}\n\n"
                        judge_decision = fast_judge_triage(critique_report)
                        yield f"data: {json.dumps({'type': 'fast_judge_complete', 'data': judge_decision.model_dump()})}\n\n"

                    # Verification (if escalated)
                        verification_report = None
                        if judge_decision.decision.value == "escalate_for_verification":
                            yield f"data: {json.dumps({'type': 'verification_start'})}\n\n"
                            targets = select_verification_targets(judge_decision, critique_report, stage1_results)
                            if targets:
                                verification_report = await run_verification(targets)
                            yield f"data: {json.dumps({'type': 'verification_complete', 'data': verification_report.model_dump() if verification_report else {}})}\n\n"

                    # Post-verification judge
                        final_decision = post_verification_judge(critique_report, judge_decision, verification_report)
                        yield f"data: {json.dumps({'type': 'post_judge_complete', 'data': final_decision.model_dump()})}\n\n"

                        message_metadata = {
                            'label_to_model': label_to_model,
                            'aggregate_rankings': aggregate_rankings,
                            'critique_report': critique_report.model_dump() if critique_report else None,
                            'judge_decision': judge_decision.model_dump(),
                            'verification_report': verification_report.model_dump() if verification_report else None,
                            'final_decision': final_decision.model_dump(),
                            'trace': trace_payload,
                        }

                    # Check if a second round is needed
                        if final_decision.decision == FinalDecisionType.second_round:
                            second_round_start_event = {'type': 'second_round_start', 'data': {'round': 1, 'rationale': final_decision.rationale}}
                            yield f"data: {json.dumps(second_round_start_event)}\n\n"

                        # Run second round — this may recurse up to MAX_ROUNDS times
                            stage1_results, stage2_results, stage3_result, metadata = await run_second_round(
                                council_query, final_decision, stage1_results,
                                critique_report=critique_report,
                                verification_report=verification_report,
                                round_number=1
                            )

                        # Emit second round completion with all metadata
                            second_round_complete_event = {
                                'type': 'second_round_complete',
                                'data': {
                                    'round_number': metadata.get('round_number', 1),
                                    'final_decision': metadata.get('final_decision'),
                                    'research_briefing': metadata.get('research_briefing'),
                                }
                            }
                            yield f"data: {json.dumps(second_round_complete_event)}\n\n"

                            message_metadata = metadata

                        # Re-emit stage2 and stage3 with second-round data
                            label_to_model = metadata.get('label_to_model', label_to_model)
                            aggregate_rankings = metadata.get('aggregate_rankings', aggregate_rankings)

                            stage2_complete_event = {
                                'type': 'stage2_complete',
                                'data': stage2_results,
                                'metadata': {
                                    'label_to_model': label_to_model,
                                    'aggregate_rankings': aggregate_rankings,
                                    'trace': metadata.get('trace', trace_payload),
                                    'critique_report': metadata.get('critique_report'),
                                },
                            }
                            yield f"data: {json.dumps(stage2_complete_event)}\n\n"

                            yield f"data: {json.dumps({'type': 'stage3_start'})}\n\n"
                            yield f"data: {json.dumps({'type': 'stage3_complete', 'data': stage3_result})}\n\n"
                        else:
                        # Stage 3: Synthesis enriched with structured data
                            yield f"data: {json.dumps({'type': 'stage3_start'})}\n\n"
                            stage3_result = await stage3_synthesize_final(
                                council_query, stage1_results, stage2_results,
                                critique_report=critique_report,
                                final_decision=final_decision,
                                verification_report=verification_report
                            )
                            yield f"data: {json.dumps({'type': 'stage3_complete', 'data': stage3_result})}\n\n"

                    except Exception as pipeline_error:
                    # Fallback to original pipeline
                        import logging
                        logging.getLogger(__name__).warning(f"Structured pipeline failed in stream, falling back: {pipeline_error}", exc_info=True)

                        yield f"data: {json.dumps({'type': 'stage2_start'})}\n\n"
                        stage2_results, label_to_model = await stage2_collect_rankings(council_query, stage1_results)
                        aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_model)
                        message_metadata = {
                            'label_to_model': label_to_model,
                            'aggregate_rankings': aggregate_rankings,
                            'critique_report': None,
                            'judge_decision': None,
                            'verification_report': None,
                            'final_decision': None,
                            'trace': trace_payload,
                        }
                        yield f"data: {json.dumps({'type': 'stage2_complete', 'data': stage2_results, 'metadata': message_metadata})}\n\n"

                        yield f"data: {json.dumps({'type': 'stage3_start'})}\n\n"
                        stage3_result = await stage3_synthesize_final(council_query, stage1_results, stage2_results)
                        yield f"data: {json.dumps({'type': 'stage3_complete', 'data': stage3_result})}\n\n"

                    # Wait for title generation if it was started
                    if title_task:
                        title = await title_task
                        storage.update_conversation_title(conversation_id, title)
                        yield f"data: {json.dumps({'type': 'title_complete', 'data': {'title': title}})}\n\n"

                    # Save complete assistant message
                    storage.add_assistant_message(
                        conversation_id,
                        stage1_results,
                        stage2_results,
                        stage3_result,
                        metadata=message_metadata,
                        trace=trace_payload,
                    )

                    span.set_output({
                        "stage3_model": stage3_result.get("model"),
                        "stage3_response_characters": len(stage3_result.get("response", "")),
                        "stream_completed": True,
                        "trace": trace_payload,
                    })
                    mark_span_ok(span)

                    # Send completion event
                    yield f"data: {json.dumps({'type': 'complete', 'data': {'trace': trace_payload}})}\n\n"

                except Exception as e:
                    mark_span_error(span, e)
                    # Send error event
                    yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=BACKEND_HOST, port=BACKEND_PORT)
