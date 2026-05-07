"""JSON-based storage for conversations."""

import json
import os
import re
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path
from .config import DATA_DIR, RESEARCH_LOG_DIR


def ensure_data_dir():
    """Ensure the data directory exists."""
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)


def ensure_research_log_dir():
    """Ensure the repo-local research log directory exists."""
    Path(RESEARCH_LOG_DIR).mkdir(parents=True, exist_ok=True)


def get_conversation_path(conversation_id: str) -> str:
    """Get the file path for a conversation."""
    return os.path.join(DATA_DIR, f"{conversation_id}.json")


def create_conversation(conversation_id: str) -> Dict[str, Any]:
    """
    Create a new conversation.

    Args:
        conversation_id: Unique identifier for the conversation

    Returns:
        New conversation dict
    """
    ensure_data_dir()

    conversation = {
        "id": conversation_id,
        "created_at": datetime.utcnow().isoformat(),
        "title": "New Conversation",
        "research_context": None,
        "messages": []
    }

    # Save to file
    path = get_conversation_path(conversation_id)
    with open(path, 'w') as f:
        json.dump(conversation, f, indent=2)

    return conversation


def get_conversation(conversation_id: str) -> Optional[Dict[str, Any]]:
    """
    Load a conversation from storage.

    Args:
        conversation_id: Unique identifier for the conversation

    Returns:
        Conversation dict or None if not found
    """
    path = get_conversation_path(conversation_id)

    if not os.path.exists(path):
        return None

    with open(path, 'r') as f:
        return json.load(f)


def save_conversation(conversation: Dict[str, Any]):
    """
    Save a conversation to storage.

    Args:
        conversation: Conversation dict to save
    """
    ensure_data_dir()

    path = get_conversation_path(conversation['id'])
    with open(path, 'w') as f:
        json.dump(conversation, f, indent=2)


def list_conversations() -> List[Dict[str, Any]]:
    """
    List all conversations (metadata only).

    Returns:
        List of conversation metadata dicts
    """
    ensure_data_dir()

    conversations = []
    for filename in os.listdir(DATA_DIR):
        if filename.endswith('.json'):
            path = os.path.join(DATA_DIR, filename)
            with open(path, 'r') as f:
                data = json.load(f)
                # Return metadata only
                conversations.append({
                    "id": data["id"],
                    "created_at": data["created_at"],
                    "title": data.get("title", "New Conversation"),
                    "message_count": len(data["messages"])
                })

    # Sort by creation time, newest first
    conversations.sort(key=lambda x: x["created_at"], reverse=True)

    return conversations


def add_user_message(conversation_id: str, content: str):
    """
    Add a user message to a conversation.

    Args:
        conversation_id: Conversation identifier
        content: User message content
    """
    conversation = get_conversation(conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")

    conversation["messages"].append({
        "role": "user",
        "content": content
    })

    save_conversation(conversation)


def add_assistant_message(
    conversation_id: str,
    stage1: List[Dict[str, Any]],
    stage2: List[Dict[str, Any]],
    stage3: Dict[str, Any],
    metadata: Optional[Dict[str, Any]] = None,
    trace: Optional[Dict[str, Any]] = None,
):
    """
    Add an assistant message with all 3 stages to a conversation.

    Args:
        conversation_id: Conversation identifier
        stage1: List of individual model responses
        stage2: List of model rankings
        stage3: Final synthesized response
        metadata: Structured council metadata to persist with the message
        trace: Optional trace metadata for observability links
    """
    conversation = get_conversation(conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")

    assistant_message = {
        "role": "assistant",
        "stage1": stage1,
        "stage2": stage2,
        "stage3": stage3,
    }

    if metadata:
        assistant_message["metadata"] = metadata
        if metadata.get("critique_report"):
            assistant_message["critiqueReport"] = metadata["critique_report"]
        if metadata.get("judge_decision"):
            assistant_message["judgeDecision"] = metadata["judge_decision"]
        if metadata.get("verification_report"):
            assistant_message["verificationReport"] = metadata["verification_report"]
        if metadata.get("final_decision"):
            assistant_message["finalDecision"] = metadata["final_decision"]
        if metadata.get("second_round"):
            final_decision = metadata.get("final_decision") or {}
            assistant_message["secondRound"] = {
                "round": metadata.get("round_number", 1),
                "rationale": final_decision.get("rationale", ""),
                "research_briefing": metadata.get("research_briefing"),
            }
        if metadata.get("trace"):
            assistant_message["trace"] = metadata["trace"]

    if trace:
        assistant_message["trace"] = trace

    conversation["messages"].append(assistant_message)

    save_conversation(conversation)


def update_conversation_title(conversation_id: str, title: str):
    """
    Update the title of a conversation.

    Args:
        conversation_id: Conversation identifier
        title: New title for the conversation
    """
    conversation = get_conversation(conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")

    conversation["title"] = title
    save_conversation(conversation)


def _safe_filename(value: str, default: str = "research-log") -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip().lower()).strip("-._")
    return cleaned[:80] or default


def _json_block(value: Any) -> str:
    return "```json\n" + json.dumps(value, indent=2, ensure_ascii=False) + "\n```"


def render_conversation_markdown(conversation: Dict[str, Any]) -> str:
    """Render the complete conversation as a portable research log."""
    title = conversation.get("title") or "LLM Council Research Log"
    lines = [
        f"# {title}",
        "",
        f"- Conversation ID: `{conversation.get('id', '')}`",
        f"- Created: `{conversation.get('created_at', '')}`",
        f"- Exported: `{datetime.utcnow().isoformat()}`",
        "",
    ]

    research_context = conversation.get("research_context")
    if research_context:
        lines.extend([
            "## Loaded Research Context",
            "",
            f"Source: `{research_context.get('filename', 'uploaded context')}`",
            "",
            "```markdown",
            research_context.get("content", ""),
            "```",
            "",
        ])

    for index, message in enumerate(conversation.get("messages", []), start=1):
        role = message.get("role", "message").title()
        lines.extend([f"## {index}. {role}", ""])

        if message.get("role") == "user":
            lines.extend([message.get("content", ""), ""])
            continue

        stage1 = message.get("stage1") or []
        if stage1:
            lines.extend(["### Stage 1: Specialist Responses", ""])
            for response in stage1:
                lines.extend([
                    f"#### {response.get('model', 'unknown model')}",
                    "",
                    response.get("response", ""),
                    "",
                ])
                if response.get("reasoning") or response.get("reasoning_details"):
                    lines.extend([
                        "<details><summary>Reasoning artifacts</summary>",
                        "",
                        _json_block({
                            "reasoning": response.get("reasoning"),
                            "reasoning_details": response.get("reasoning_details"),
                            "usage": response.get("usage"),
                        }),
                        "",
                        "</details>",
                        "",
                    ])

        stage2 = message.get("stage2") or []
        if stage2:
            lines.extend(["### Stage 2: Peer Critique", ""])
            for critique in stage2:
                lines.extend([
                    f"#### {critique.get('model', 'unknown model')}",
                    "",
                    critique.get("ranking", ""),
                    "",
                ])
                if critique.get("reasoning") or critique.get("reasoning_details"):
                    lines.extend([
                        "<details><summary>Reasoning artifacts</summary>",
                        "",
                        _json_block({
                            "reasoning": critique.get("reasoning"),
                            "reasoning_details": critique.get("reasoning_details"),
                            "usage": critique.get("usage"),
                        }),
                        "",
                        "</details>",
                        "",
                    ])

        stage3 = message.get("stage3") or {}
        if stage3:
            lines.extend([
                "### Stage 3: Chairman Synthesis",
                "",
                f"Chairman: `{stage3.get('model', 'unknown model')}`",
                "",
                stage3.get("response", ""),
                "",
            ])
            if stage3.get("reasoning") or stage3.get("reasoning_details"):
                lines.extend([
                    "<details><summary>Reasoning artifacts</summary>",
                    "",
                    _json_block({
                        "reasoning": stage3.get("reasoning"),
                        "reasoning_details": stage3.get("reasoning_details"),
                        "usage": stage3.get("usage"),
                    }),
                    "",
                    "</details>",
                    "",
                ])

        metadata = message.get("metadata")
        if metadata:
            lines.extend([
                "<details><summary>Structured metadata</summary>",
                "",
                _json_block(metadata),
                "",
                "</details>",
                "",
            ])

    return "\n".join(lines).rstrip() + "\n"


def export_conversation(conversation_id: str, export_format: str = "markdown") -> Dict[str, Any]:
    """Return a conversation export payload in markdown or JSON format."""
    conversation = get_conversation(conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")

    slug = _safe_filename(conversation.get("title") or conversation_id)
    if export_format == "json":
        return {
            "filename": f"{slug}-{conversation_id[:8]}.json",
            "content_type": "application/json",
            "content": json.dumps(conversation, indent=2, ensure_ascii=False),
        }

    return {
        "filename": f"{slug}-{conversation_id[:8]}.md",
        "content_type": "text/markdown",
        "content": render_conversation_markdown(conversation),
    }


def save_research_log(conversation_id: str) -> Dict[str, Any]:
    """Render and save a conversation markdown log into the repo-local log folder."""
    export = export_conversation(conversation_id, "markdown")
    ensure_research_log_dir()
    path = Path(RESEARCH_LOG_DIR) / export["filename"]
    path.write_text(export["content"], encoding="utf-8")
    return {
        "filename": export["filename"],
        "path": str(path),
        "content": export["content"],
        "saved_at": datetime.utcnow().isoformat(),
    }


def list_research_logs() -> List[Dict[str, Any]]:
    """List saved markdown research logs."""
    ensure_research_log_dir()
    logs = []
    for path in Path(RESEARCH_LOG_DIR).glob("*.md"):
        stat = path.stat()
        logs.append({
            "filename": path.name,
            "path": str(path),
            "size_bytes": stat.st_size,
            "modified_at": datetime.utcfromtimestamp(stat.st_mtime).isoformat(),
        })
    logs.sort(key=lambda item: item["modified_at"], reverse=True)
    return logs


def _resolve_research_log_path(filename: str) -> Path:
    ensure_research_log_dir()
    requested = Path(filename)
    if requested.is_absolute() or ".." in requested.parts:
        raise ValueError("Research log filename must stay inside the research log directory")
    path = Path(RESEARCH_LOG_DIR) / requested.name
    if not path.exists():
        raise ValueError(f"Research log {requested.name} not found")
    return path


def read_research_log(filename: str) -> Dict[str, Any]:
    """Read a saved research log by filename."""
    path = _resolve_research_log_path(filename)
    return {
        "filename": path.name,
        "path": str(path),
        "content": path.read_text(encoding="utf-8"),
    }


def set_research_context(conversation_id: str, filename: str, content: str) -> Dict[str, Any]:
    """Attach uploaded or saved research context to a conversation."""
    conversation = get_conversation(conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")

    conversation["research_context"] = {
        "filename": filename or "uploaded research context",
        "content": content,
        "loaded_at": datetime.utcnow().isoformat(),
    }
    save_conversation(conversation)
    return conversation["research_context"]


def clear_research_context(conversation_id: str) -> Dict[str, Any]:
    """Remove any attached research context from a conversation."""
    conversation = get_conversation(conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")
    conversation["research_context"] = None
    save_conversation(conversation)
    return {"research_context": None}


def build_contextual_user_query(conversation: Dict[str, Any], user_content: str) -> str:
    """Prepend loaded research context to the next council prompt when present."""
    research_context = conversation.get("research_context")
    if not research_context or not research_context.get("content"):
        return user_content

    return "\n".join([
        "You are continuing a research and development ideation thread.",
        "Use the loaded research context as persistent project memory, but prioritize the user's latest request.",
        "",
        f"LOADED RESEARCH FILE: {research_context.get('filename', 'research context')}",
        "```markdown",
        research_context.get("content", ""),
        "```",
        "",
        "LATEST USER REQUEST:",
        user_content,
    ])
