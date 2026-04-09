"""Configuration for the LLM Council.

Supports both environment-variable defaults and runtime configuration
via a JSON file (data/config.json). Runtime config takes precedence.
"""

import json
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# OpenRouter API key
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# OpenRouter API endpoint
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Data directory for conversation storage
DATA_DIR = "data/conversations"

# Config file path
CONFIG_FILE = "data/config.json"

# Default council configuration
DEFAULT_COUNCIL_MODELS = [
    "openai/gpt-5.1",
    "google/gemini-3-pro-preview",
    "anthropic/claude-sonnet-4.5",
    "x-ai/grok-4",
]

DEFAULT_CHAIRMAN_MODEL = "google/gemini-3-pro-preview"

# Available models for selection (popular OpenRouter models)
AVAILABLE_MODELS = [
    {"id": "openai/gpt-5.1", "name": "GPT-5.1", "provider": "OpenAI"},
    {"id": "google/gemini-3-pro-preview", "name": "Gemini 3 Pro", "provider": "Google"},
    {"id": "anthropic/claude-sonnet-4.5", "name": "Claude Sonnet 4.5", "provider": "Anthropic"},
    {"id": "x-ai/grok-4", "name": "Grok-4", "provider": "xAI"},
    {"id": "openai/gpt-4o", "name": "GPT-4o", "provider": "OpenAI"},
    {"id": "anthropic/claude-opus-4", "name": "Claude Opus 4", "provider": "Anthropic"},
    {"id": "google/gemini-2.5-flash", "name": "Gemini 2.5 Flash", "provider": "Google"},
    {"id": "meta-llama/llama-4-maverick", "name": "Llama 4 Maverick", "provider": "Meta"},
    {"id": "deepseek/deepseek-r1", "name": "DeepSeek R1", "provider": "DeepSeek"},
    {"id": "mistralai/mistral-large-3", "name": "Mistral Large 3", "provider": "Mistral"},
]


def _ensure_data_dir():
    """Ensure the data directory exists."""
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    """Load runtime configuration from JSON file.

    Returns:
        Dict with 'council_models' and 'chairman_model' keys.
        Falls back to defaults if config file doesn't exist.
    """
    _ensure_data_dir()
    config_path = Path(CONFIG_FILE)
    if config_path.exists():
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
            return {
                "council_models": config.get("council_models", DEFAULT_COUNCIL_MODELS),
                "chairman_model": config.get("chairman_model", DEFAULT_CHAIRMAN_MODEL),
            }
        except (json.JSONDecodeError, IOError):
            pass
    return {
        "council_models": DEFAULT_COUNCIL_MODELS,
        "chairman_model": DEFAULT_CHAIRMAN_MODEL,
    }


def save_config(council_models: list, chairman_model: str) -> dict:
    """Save runtime configuration to JSON file.

    Args:
        council_models: List of model identifiers for council members.
        chairman_model: Model identifier for the chairman.

    Returns:
        The saved configuration dict.
    """
    _ensure_data_dir()
    config = {
        "council_models": council_models,
        "chairman_model": chairman_model,
    }
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)
    return config


def get_council_models() -> list:
    """Get the current list of council models."""
    return load_config()["council_models"]


def get_chairman_model() -> str:
    """Get the current chairman model."""
    return load_config()["chairman_model"]
