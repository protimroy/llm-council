"""MCP server exposing LLM Council as tools.

Run with:
    uv run python -m backend.mcp_server

This keeps MCP integration optional and separate from the FastAPI app.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .config import AVAILABLE_MODELS, load_config, save_config
from .council import run_full_council
from .langgraph_pipeline import run_full_council_langgraph
from .observability import get_current_trace_payload, get_tracer, using_trace_context
from .openrouter import fetch_openrouter_models

tracer = get_tracer(__name__)

mcp = FastMCP(
    name="llm-council",
    instructions=(
        "Use these tools to run the LLM Council pipeline, inspect its configuration, "
        "and update the active council models."
    ),
)


@mcp.tool()
@tracer.tool(name="mcp.run_council")
async def run_council(query: str) -> dict:
    """Run the default council pipeline for a user query."""
    with using_trace_context(request_transport="mcp", council_engine="default", request_mode="tool"):
        stage1, stage2, stage3, metadata = await run_full_council(query)
        return {
            "stage1": stage1,
            "stage2": stage2,
            "stage3": stage3,
            "metadata": metadata,
            "trace": get_current_trace_payload(),
        }


@mcp.tool()
@tracer.tool(name="mcp.run_council_langgraph")
async def run_council_langgraph(query: str) -> dict:
    """Run the LangGraph-backed council pipeline for a user query."""
    with using_trace_context(request_transport="mcp", council_engine="langgraph", request_mode="tool"):
        stage1, stage2, stage3, metadata = await run_full_council_langgraph(query)
        return {
            "stage1": stage1,
            "stage2": stage2,
            "stage3": stage3,
            "metadata": metadata,
            "trace": get_current_trace_payload(),
        }


@mcp.tool()
@tracer.tool(name="mcp.get_council_config")
def get_council_config() -> dict:
    """Get the currently active council configuration."""
    return load_config()


@mcp.tool()
@tracer.tool(name="mcp.list_available_models")
async def list_available_models() -> dict:
    """List the models available for council configuration."""
    catalog = await fetch_openrouter_models()
    return {
        "available_models": catalog.get("available_models") or AVAILABLE_MODELS,
        "model_source": catalog.get("source"),
        "model_catalog_error": catalog.get("error"),
    }


@mcp.tool()
@tracer.tool(name="mcp.update_council_config")
def update_council_config(council_models: list[str], chairman_model: str) -> dict:
    """Update the active council configuration."""
    return save_config(council_models, chairman_model)


if __name__ == "__main__":
    mcp.run()
