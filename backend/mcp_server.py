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

mcp = FastMCP(
    name="llm-council",
    instructions=(
        "Use these tools to run the LLM Council pipeline, inspect its configuration, "
        "and update the active council models."
    ),
)


@mcp.tool()
async def run_council(query: str) -> dict:
    """Run the default council pipeline for a user query."""
    stage1, stage2, stage3, metadata = await run_full_council(query)
    return {
        "stage1": stage1,
        "stage2": stage2,
        "stage3": stage3,
        "metadata": metadata,
    }


@mcp.tool()
async def run_council_langgraph(query: str) -> dict:
    """Run the LangGraph-backed council pipeline for a user query."""
    stage1, stage2, stage3, metadata = await run_full_council_langgraph(query)
    return {
        "stage1": stage1,
        "stage2": stage2,
        "stage3": stage3,
        "metadata": metadata,
    }


@mcp.tool()
def get_council_config() -> dict:
    """Get the currently active council configuration."""
    return load_config()


@mcp.tool()
def list_available_models() -> dict:
    """List the models available for council configuration."""
    return {"available_models": AVAILABLE_MODELS}


@mcp.tool()
def update_council_config(council_models: list[str], chairman_model: str) -> dict:
    """Update the active council configuration."""
    return save_config(council_models, chairman_model)


if __name__ == "__main__":
    mcp.run()
