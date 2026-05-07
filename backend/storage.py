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
        "research_session": None,
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


def _utc_now() -> str:
    return datetime.utcnow().isoformat()


def _first_markdown_heading(content: str, default: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip() or default
    return default


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


def _resolve_research_session_dir(session_id: str) -> Path:
    ensure_research_log_dir()
    requested = Path(session_id)
    if requested.is_absolute() or ".." in requested.parts or len(requested.parts) != 1:
        raise ValueError("Research session id must stay inside the research log directory")
    path = Path(RESEARCH_LOG_DIR) / requested.name
    if not path.exists() or not path.is_dir() or not (path / "session.json").exists():
        raise ValueError(f"Research session {requested.name} not found")
    return path


def _read_session_metadata(session_path: Path) -> Dict[str, Any]:
    metadata_path = session_path / "session.json"
    return json.loads(metadata_path.read_text(encoding="utf-8"))


def _write_session_metadata(session_path: Path, metadata: Dict[str, Any]) -> None:
    metadata["updated_at"] = _utc_now()
    (session_path / "session.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _default_plan_markdown(title: str, seed_content: Optional[str] = None) -> str:
    lines = [
        f"# {title}",
        "",
        "Tags: #research-session #plan",
        "Links: [[research_log]]",
        "",
        "## Problem Statement",
        "",
        "## Hypotheses",
        "",
        "## Assumptions",
        "",
        "## Unknowns",
        "",
        "## Experiments",
        "",
        "## Success Criteria",
        "",
        "## Next Actions",
        "",
    ]
    if seed_content:
        lines.extend(["## Seed Notes", "", seed_content.strip(), ""])
    return "\n".join(lines).rstrip() + "\n"


def _default_log_markdown(title: str, seed_content: Optional[str] = None) -> str:
    lines = [
        f"# {title} Research Log",
        "",
        "Tags: #research-session #research-log",
        "Links: [[plan]]",
        "",
        f"## {_utc_now()}",
        "",
        "Research session created.",
        "",
    ]
    if seed_content:
        lines.extend(["### Seed", "", seed_content.strip(), ""])
    return "\n".join(lines).rstrip() + "\n"


def _session_file_payload(path: Path) -> Dict[str, Any]:
    content = path.read_text(encoding="utf-8")
    stat = path.stat()
    return {
        "filename": path.name,
        "path": str(path),
        "title": _first_markdown_heading(content, path.stem.replace("_", " ").title()),
        "content": content,
        "size_bytes": stat.st_size,
        "modified_at": datetime.utcfromtimestamp(stat.st_mtime).isoformat(),
    }


def create_research_session(
    title: str,
    seed_content: Optional[str] = None,
    conversation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a repo-local research session folder with plan and log files."""
    ensure_research_log_dir()
    clean_title = title.strip() or "Research Session"
    slug = _safe_filename(clean_title, "research-session")
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    session_id = f"{slug}-{timestamp}"
    session_path = Path(RESEARCH_LOG_DIR) / session_id
    session_path.mkdir(parents=True, exist_ok=False)

    now = _utc_now()
    metadata = {
        "id": session_id,
        "title": clean_title,
        "created_at": now,
        "updated_at": now,
        "conversation_id": conversation_id,
        "files": ["plan.md", "research_log.md"],
    }
    (session_path / "plan.md").write_text(_default_plan_markdown(clean_title, seed_content), encoding="utf-8")
    (session_path / "research_log.md").write_text(_default_log_markdown(clean_title, seed_content), encoding="utf-8")
    _write_session_metadata(session_path, metadata)
    return get_research_session(session_id)


def list_research_sessions() -> List[Dict[str, Any]]:
    """List repo-local research sessions."""
    ensure_research_log_dir()
    sessions = []
    for metadata_path in Path(RESEARCH_LOG_DIR).glob("*/session.json"):
        session_path = metadata_path.parent
        try:
            metadata = _read_session_metadata(session_path)
        except (json.JSONDecodeError, OSError):
            continue
        files = sorted(path.name for path in session_path.glob("*.md"))
        sessions.append({
            **metadata,
            "path": str(session_path),
            "file_count": len(files),
            "files": files,
        })
    sessions.sort(key=lambda item: item.get("updated_at", item.get("created_at", "")), reverse=True)
    return sessions


def get_research_session(session_id: str) -> Dict[str, Any]:
    """Load a research session with Markdown file contents."""
    session_path = _resolve_research_session_dir(session_id)
    metadata = _read_session_metadata(session_path)
    files = [_session_file_payload(path) for path in sorted(session_path.glob("*.md"))]
    by_name = {file["filename"]: file for file in files}
    return {
        **metadata,
        "path": str(session_path),
        "files": files,
        "plan": by_name.get("plan.md"),
        "research_log": by_name.get("research_log.md"),
    }


def _resolve_research_session_file(session_path: Path, filename: str) -> Path:
    requested = Path(filename)
    if requested.is_absolute() or ".." in requested.parts or len(requested.parts) != 1:
        raise ValueError("Research session files must stay inside the session directory")
    if requested.suffix.lower() not in {".md", ".markdown"}:
        raise ValueError("Research session files must be Markdown")
    return session_path / requested.name


def update_research_session_file(session_id: str, filename: str, content: str) -> Dict[str, Any]:
    """Create or replace a Markdown file inside a research session."""
    session_path = _resolve_research_session_dir(session_id)
    path = _resolve_research_session_file(session_path, filename)
    path.write_text(content, encoding="utf-8")
    metadata = _read_session_metadata(session_path)
    files = set(metadata.get("files") or [])
    files.add(path.name)
    metadata["files"] = sorted(files)
    _write_session_metadata(session_path, metadata)
    return get_research_session(session_id)


def append_research_session_log(session_id: str, content: str, source: Optional[str] = None) -> Dict[str, Any]:
    """Append a dated entry to a session research_log.md file."""
    if not content.strip():
        raise ValueError("Log entry cannot be empty")
    session_path = _resolve_research_session_dir(session_id)
    log_path = session_path / "research_log.md"
    source_line = f"Source: {source.strip()}\n\n" if source and source.strip() else ""
    entry = f"\n## {_utc_now()}\n\n{source_line}{content.strip()}\n"
    with open(log_path, "a", encoding="utf-8") as file:
        file.write(entry)
    metadata = _read_session_metadata(session_path)
    _write_session_metadata(session_path, metadata)
    return get_research_session(session_id)


def render_research_session_context(session_id: str) -> Dict[str, Any]:
    """Render all Markdown files in a research session as prompt context."""
    session = get_research_session(session_id)
    lines = [
        f"# Research Session: {session.get('title', session_id)}",
        "",
        f"Session ID: `{session.get('id', session_id)}`",
        "",
    ]
    for file in session.get("files", []):
        lines.extend([
            f"## File: {file.get('filename', 'unknown.md')}",
            "",
            "```markdown",
            file.get("content", ""),
            "```",
            "",
        ])
    return {
        "filename": f"{session_id}/session-context.md",
        "content": "\n".join(lines).rstrip() + "\n",
        "session": {
            "id": session.get("id"),
            "title": session.get("title"),
            "path": session.get("path"),
        },
    }


def set_research_context(conversation_id: str, filename: str, content: str) -> Dict[str, Any]:
    """Attach uploaded or saved research context to a conversation."""
    conversation = get_conversation(conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")

    conversation["research_context"] = {
        "filename": filename or "uploaded research context",
        "content": content,
        "loaded_at": _utc_now(),
    }
    conversation["research_session"] = None
    save_conversation(conversation)
    return conversation["research_context"]


def set_research_context_from_session(conversation_id: str, session_id: str) -> Dict[str, Any]:
    """Attach a research session's plan/log files to a conversation as context."""
    conversation = get_conversation(conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")
    session_context = render_research_session_context(session_id)
    conversation["research_context"] = {
        "filename": session_context["filename"],
        "content": session_context["content"],
        "loaded_at": _utc_now(),
    }
    conversation["research_session"] = session_context["session"]
    save_conversation(conversation)
    return {
        "research_context": conversation["research_context"],
        "research_session": conversation["research_session"],
    }


def clear_research_context(conversation_id: str) -> Dict[str, Any]:
    """Remove any attached research context from a conversation."""
    conversation = get_conversation(conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")
    conversation["research_context"] = None
    conversation["research_session"] = None
    save_conversation(conversation)
    return {"research_context": None, "research_session": None}


def _strip_fenced_code(content: str) -> str:
    return re.sub(r"```.*?```", "", content, flags=re.DOTALL)


def _markdown_documents() -> List[Dict[str, Any]]:
    ensure_research_log_dir()
    root = Path(RESEARCH_LOG_DIR)
    documents = []
    for path in sorted(root.rglob("*.md")):
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8")
        relative_path = path.relative_to(root).as_posix()
        stat = path.stat()
        documents.append({
            "id": relative_path,
            "path": str(path),
            "relative_path": relative_path,
            "filename": path.name,
            "title": _first_markdown_heading(content, path.stem.replace("_", " ").title()),
            "content": content,
            "session_id": path.parent.name if (path.parent / "session.json").exists() else None,
            "size_bytes": stat.st_size,
            "modified_at": datetime.utcfromtimestamp(stat.st_mtime).isoformat(),
        })
    return documents


def _resolve_document_link(target: str, source_id: str, document_ids: set[str], by_stem: Dict[str, str]) -> Optional[str]:
    clean_target = target.split("|", 1)[0].split("#", 1)[0].strip().replace("\\", "/")
    if not clean_target or "://" in clean_target or clean_target.startswith("mailto:"):
        return None
    clean_target = clean_target.lstrip("/")
    with_suffix = clean_target if clean_target.lower().endswith((".md", ".markdown")) else f"{clean_target}.md"
    source_parent = Path(source_id).parent
    candidates = []
    if str(source_parent) != ".":
        candidates.append((source_parent / with_suffix).as_posix())
    candidates.extend([with_suffix, clean_target])
    for candidate in candidates:
        if candidate in document_ids:
            return candidate
    return by_stem.get(Path(clean_target).stem.lower())


def build_research_graph() -> Dict[str, Any]:
    """Build an Obsidian-style graph from explicit Markdown links and tags."""
    documents = _markdown_documents()
    document_ids = {document["id"] for document in documents}
    by_stem = {Path(document["id"]).stem.lower(): document["id"] for document in documents}
    nodes: Dict[str, Dict[str, Any]] = {}
    edges: Dict[tuple[str, str, str], Dict[str, Any]] = {}

    for document in documents:
        nodes[document["id"]] = {
            "id": document["id"],
            "label": document["title"],
            "type": "document",
            "path": document["relative_path"],
            "session_id": document.get("session_id"),
            "size_bytes": document.get("size_bytes"),
            "modified_at": document.get("modified_at"),
        }

    wiki_link_pattern = re.compile(r"\[\[([^\]]+)\]\]")
    markdown_link_pattern = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
    tag_pattern = re.compile(r"(?<![\w/])#([A-Za-z][A-Za-z0-9_-]{1,48})")

    for document in documents:
        source = document["id"]
        searchable_content = _strip_fenced_code(document["content"])
        raw_links = wiki_link_pattern.findall(searchable_content) + markdown_link_pattern.findall(searchable_content)
        for raw_link in raw_links:
            target = _resolve_document_link(raw_link, source, document_ids, by_stem)
            if target:
                edges[(source, target, "link")] = {"source": source, "target": target, "type": "link"}
            else:
                missing_label = raw_link.split("|", 1)[0].split("#", 1)[0].strip()
                if not missing_label or "://" in missing_label:
                    continue
                missing_id = f"missing:{_safe_filename(missing_label, 'untitled-note')}"
                nodes.setdefault(missing_id, {
                    "id": missing_id,
                    "label": missing_label,
                    "type": "missing",
                    "path": None,
                })
                edges[(source, missing_id, "missing-link")] = {
                    "source": source,
                    "target": missing_id,
                    "type": "missing-link",
                }

        for tag in sorted(set(tag_pattern.findall(searchable_content))):
            tag_id = f"tag:{tag.lower()}"
            nodes.setdefault(tag_id, {
                "id": tag_id,
                "label": f"#{tag}",
                "type": "tag",
                "path": None,
            })
            edges[(source, tag_id, "tag")] = {"source": source, "target": tag_id, "type": "tag"}

    return {
        "nodes": list(nodes.values()),
        "edges": list(edges.values()),
        "generated_at": _utc_now(),
        "document_count": len(documents),
        "tag_count": len([node for node in nodes.values() if node.get("type") == "tag"]),
        "mode": "explicit-markdown-links-and-tags",
    }


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
