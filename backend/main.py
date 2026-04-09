"""FastAPI backend for LLM Council."""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Any
import uuid
import json
import asyncio

from . import storage
from .config import load_config, save_config, AVAILABLE_MODELS
from .council import (
    run_full_council, generate_conversation_title,
    stage1_collect_responses, stage2_collect_rankings, stage2_critique_claims,
    stage3_synthesize_final, calculate_aggregate_rankings, aggregate_from_critique,
    run_second_round,
)
from .langgraph_pipeline import run_full_council_langgraph
from .models import FinalDecisionType
from .judge import fast_judge_triage, select_verification_targets, post_verification_judge
from .verification import run_verification

app = FastAPI(title="LLM Council API")

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
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
    messages: List[Dict[str, Any]]


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "service": "LLM Council API"}


@app.get("/api/models")
async def list_models():
    """List available models and current council configuration."""
    current_config = load_config()
    return {
        "available_models": AVAILABLE_MODELS,
        "current_config": current_config,
    }


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


@app.post("/api/conversations/{conversation_id}/message")
async def send_message(conversation_id: str, request: SendMessageRequest):
    """
    Send a message and run the 3-stage council process.
    Returns the complete response with all stages.
    """
    # Check if conversation exists
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check if this is the first message
    is_first_message = len(conversation["messages"]) == 0

    # Add user message
    storage.add_user_message(conversation_id, request.content)

    # If this is the first message, generate a title
    if is_first_message:
        title = await generate_conversation_title(request.content)
        storage.update_conversation_title(conversation_id, title)

    # Run the 3-stage council process
    stage1_results, stage2_results, stage3_result, metadata = await run_full_council(
        request.content
    )

    # Add assistant message with all stages
    storage.add_assistant_message(
        conversation_id,
        stage1_results,
        stage2_results,
        stage3_result
    )

    # Return the complete response with metadata
    return {
        "stage1": stage1_results,
        "stage2": stage2_results,
        "stage3": stage3_result,
        "metadata": metadata
    }


@app.post("/api/conversations/{conversation_id}/message/langgraph")
async def send_message_langgraph(conversation_id: str, request: SendMessageRequest):
    """Send a message and run the LangGraph-backed council process."""
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    is_first_message = len(conversation["messages"]) == 0
    storage.add_user_message(conversation_id, request.content)

    if is_first_message:
        title = await generate_conversation_title(request.content)
        storage.update_conversation_title(conversation_id, title)

    stage1_results, stage2_results, stage3_result, metadata = await run_full_council_langgraph(
        request.content
    )

    storage.add_assistant_message(
        conversation_id,
        stage1_results,
        stage2_results,
        stage3_result,
    )

    return {
        "stage1": stage1_results,
        "stage2": stage2_results,
        "stage3": stage3_result,
        "metadata": metadata,
    }


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
        try:
            # Add user message
            storage.add_user_message(conversation_id, request.content)

            # Start title generation in parallel (don't await yet)
            title_task = None
            if is_first_message:
                title_task = asyncio.create_task(generate_conversation_title(request.content))

            # Stage 1: Collect responses (with evidence packets)
            yield f"data: {json.dumps({'type': 'stage1_start'})}\n\n"
            stage1_results = await stage1_collect_responses(request.content)
            yield f"data: {json.dumps({'type': 'stage1_complete', 'data': stage1_results})}\n\n"

            # Try the new structured pipeline
            try:
                # Stage 2: Claim-level critique
                yield f"data: {json.dumps({'type': 'stage2_start'})}\n\n"
                stage2_results, label_to_model, critique_report = await stage2_critique_claims(request.content, stage1_results)
                aggregate_rankings = aggregate_from_critique(critique_report, label_to_model)
                stage2_metadata = {
                    'label_to_model': label_to_model,
                    'aggregate_rankings': aggregate_rankings,
                    'critique_report': critique_report.model_dump() if critique_report else None,
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

                # Check if a second round is needed
                if final_decision.decision == FinalDecisionType.second_round:
                    second_round_start_event = {'type': 'second_round_start', 'data': {'round': 1, 'rationale': final_decision.rationale}}
                    yield f"data: {json.dumps(second_round_start_event)}\n\n"

                    # Run second round — this may recurse up to MAX_ROUNDS times
                    stage1_results, stage2_results, stage3_result, metadata = await run_second_round(
                        request.content, final_decision, stage1_results,
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
                        }
                    }
                    yield f"data: {json.dumps(second_round_complete_event)}\n\n"

                    # Re-emit stage2 and stage3 with second-round data
                    label_to_model = metadata.get('label_to_model', label_to_model)
                    aggregate_rankings = metadata.get('aggregate_rankings', aggregate_rankings)

                    stage2_complete_event = {'type': 'stage2_complete', 'data': stage2_results, 'metadata': {'label_to_model': label_to_model, 'aggregate_rankings': aggregate_rankings}}
                    yield f"data: {json.dumps(stage2_complete_event)}\n\n"

                    yield f"data: {json.dumps({'type': 'stage3_start'})}\n\n"
                    yield f"data: {json.dumps({'type': 'stage3_complete', 'data': stage3_result})}\n\n"
                else:
                    # Stage 3: Synthesis enriched with structured data
                    yield f"data: {json.dumps({'type': 'stage3_start'})}\n\n"
                    stage3_result = await stage3_synthesize_final(
                        request.content, stage1_results, stage2_results,
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
                stage2_results, label_to_model = await stage2_collect_rankings(request.content, stage1_results)
                aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_model)
                yield f"data: {json.dumps({'type': 'stage2_complete', 'data': stage2_results, 'metadata': {'label_to_model': label_to_model, 'aggregate_rankings': aggregate_rankings}})}\n\n"

                yield f"data: {json.dumps({'type': 'stage3_start'})}\n\n"
                stage3_result = await stage3_synthesize_final(request.content, stage1_results, stage2_results)
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
                stage3_result
            )

            # Send completion event
            yield f"data: {json.dumps({'type': 'complete'})}\n\n"

        except Exception as e:
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
    uvicorn.run(app, host="0.0.0.0", port=8001)
