"""OpenRouter API client for making LLM requests."""

import httpx
import logging
import time
from typing import List, Dict, Any, Optional
from .config import (
    AVAILABLE_MODELS,
    OPENROUTER_API_KEY,
    OPENROUTER_API_URL,
    OPENROUTER_INCLUDE_REASONING,
    OPENROUTER_MODELS_CACHE_SECONDS,
    OPENROUTER_MODELS_URL,
)
from .observability import apply_context_to_current_span, get_tracer, mark_span_error, mark_span_ok, set_span_attributes

logger = logging.getLogger(__name__)
tracer = get_tracer(__name__)
_MODEL_CATALOG_CACHE: Optional[List[Dict[str, Any]]] = None
_MODEL_CATALOG_FETCHED_AT = 0.0


def _is_configured_api_key(api_key: Optional[str]) -> bool:
    return bool(api_key and api_key.strip() and api_key != "None")


def _provider_from_model(raw_model: Dict[str, Any]) -> str:
    name = raw_model.get("name") or ""
    if ":" in name:
        return name.split(":", 1)[0].strip()
    model_id = raw_model.get("id") or ""
    provider_slug = model_id.split("/", 1)[0] if "/" in model_id else model_id
    return provider_slug.replace("-", " ").title() or "Other"


def _normalize_catalog_model(raw_model: Dict[str, Any]) -> Dict[str, Any]:
    pricing = raw_model.get("pricing") or {}
    architecture = raw_model.get("architecture") or {}
    top_provider = raw_model.get("top_provider") or {}
    supported_parameters = raw_model.get("supported_parameters") or []

    return {
        "id": raw_model.get("id", ""),
        "name": raw_model.get("name") or raw_model.get("id", "Unknown model"),
        "provider": _provider_from_model(raw_model),
        "description": raw_model.get("description") or "",
        "context_length": raw_model.get("context_length") or top_provider.get("context_length"),
        "max_completion_tokens": top_provider.get("max_completion_tokens"),
        "input_modalities": architecture.get("input_modalities") or [],
        "output_modalities": architecture.get("output_modalities") or [],
        "pricing": {
            "prompt": pricing.get("prompt"),
            "completion": pricing.get("completion"),
        },
        "supported_parameters": supported_parameters,
        "supports_reasoning": "include_reasoning" in supported_parameters or "reasoning" in supported_parameters,
        "created": raw_model.get("created"),
        "canonical_slug": raw_model.get("canonical_slug"),
    }


def _fallback_catalog() -> List[Dict[str, Any]]:
    return [
        {
            **model,
            "description": "Static fallback model entry.",
            "context_length": None,
            "max_completion_tokens": None,
            "input_modalities": ["text"],
            "output_modalities": ["text"],
            "pricing": {"prompt": None, "completion": None},
            "supported_parameters": [],
            "supports_reasoning": False,
            "created": None,
            "canonical_slug": None,
        }
        for model in AVAILABLE_MODELS
    ]


async def fetch_openrouter_models(force_refresh: bool = False) -> Dict[str, Any]:
    """Fetch and cache the complete OpenRouter model catalog."""
    global _MODEL_CATALOG_CACHE, _MODEL_CATALOG_FETCHED_AT

    now = time.time()
    cache_is_fresh = (
        _MODEL_CATALOG_CACHE is not None
        and now - _MODEL_CATALOG_FETCHED_AT < OPENROUTER_MODELS_CACHE_SECONDS
    )
    if cache_is_fresh and not force_refresh:
        return {
            "available_models": _MODEL_CATALOG_CACHE,
            "source": "openrouter-cache",
            "fetched_at": _MODEL_CATALOG_FETCHED_AT,
            "error": None,
        }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(OPENROUTER_MODELS_URL)
            response.raise_for_status()
            data = response.json()
        raw_models = data.get("data") or []
        models = [
            _normalize_catalog_model(raw_model)
            for raw_model in raw_models
            if raw_model.get("id")
        ]
        models.sort(key=lambda model: (model.get("provider", ""), model.get("name", "")))
        _MODEL_CATALOG_CACHE = models
        _MODEL_CATALOG_FETCHED_AT = now
        return {
            "available_models": models,
            "source": "openrouter",
            "fetched_at": now,
            "error": None,
        }
    except Exception as exc:
        logger.warning("Unable to fetch OpenRouter model catalog: %s", exc)
        fallback = _MODEL_CATALOG_CACHE or _fallback_catalog()
        return {
            "available_models": fallback,
            "source": "fallback" if _MODEL_CATALOG_CACHE is None else "openrouter-cache",
            "fetched_at": _MODEL_CATALOG_FETCHED_AT or now,
            "error": str(exc),
        }


async def _model_supports_parameter(model: str, parameter: str) -> bool:
    catalog = await fetch_openrouter_models()
    for catalog_model in catalog.get("available_models", []):
        if catalog_model.get("id") == model:
            return parameter in (catalog_model.get("supported_parameters") or [])
    return False


async def query_model(
    model: str,
    messages: List[Dict[str, str]],
    timeout: float = 120.0
) -> Optional[Dict[str, Any]]:
    """
    Query a single model via OpenRouter API.

    Args:
        model: OpenRouter model identifier (e.g., "openai/gpt-4o")
        messages: List of message dicts with 'role' and 'content'
        timeout: Request timeout in seconds

    Returns:
        Response dict with 'content' and optional 'reasoning_details', or None if failed
    """
    if not _is_configured_api_key(OPENROUTER_API_KEY):
        logger.error("OpenRouter API key is not configured. Set OPENROUTER_API_KEY in .env or the process environment.")
        return None

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "messages": messages,
    }

    requested_reasoning = OPENROUTER_INCLUDE_REASONING and await _model_supports_parameter(model, "include_reasoning")
    if requested_reasoning:
        payload["include_reasoning"] = True

    with tracer.start_as_current_span(
        "openrouter.query_model",
        openinference_span_kind="llm",
    ) as span:
        span.set_input({
            "model": model,
            "message_count": len(messages),
            "timeout": timeout,
        })
        set_span_attributes(
            span,
            llm_provider="openrouter",
            llm_model_name=model,
            openrouter_url=OPENROUTER_API_URL,
            llm_message_count=len(messages),
            llm_message_roles=[message.get("role", "unknown") for message in messages],
            llm_prompt_characters=sum(len(message.get("content", "")) for message in messages),
            llm_timeout_seconds=timeout,
        )
        apply_context_to_current_span()

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    OPENROUTER_API_URL,
                    headers=headers,
                    json=payload
                )
                if response.status_code in {400, 404, 422} and payload.get("include_reasoning"):
                    retry_payload = dict(payload)
                    retry_payload.pop("include_reasoning", None)
                    logger.warning(
                        "OpenRouter rejected include_reasoning for %s; retrying without reasoning request.",
                        model,
                    )
                    response = await client.post(
                        OPENROUTER_API_URL,
                        headers=headers,
                        json=retry_payload,
                    )
                response.raise_for_status()

                data = response.json()
                message = data['choices'][0]['message']
                usage = data.get('usage')

                result = {
                    'content': message.get('content'),
                    'reasoning': message.get('reasoning'),
                    'reasoning_details': message.get('reasoning_details'),
                    'usage': usage,
                }

                if isinstance(usage, dict):
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                        value = usage.get(key)
                        if value is not None:
                            span.set_attribute(f"openrouter.usage.{key}", value)

                set_span_attributes(
                    span,
                    llm_response_characters=len(result.get("content") or ""),
                    llm_reasoning_present=bool(result.get("reasoning")),
                    llm_reasoning_details_present=bool(result.get("reasoning_details")),
                )

                span.set_output({
                    "content_characters": len(result.get("content") or ""),
                    "reasoning_present": bool(result.get("reasoning")),
                    "reasoning_details_present": bool(result.get("reasoning_details")),
                    "usage": usage,
                })
                mark_span_ok(span)
                return result

        except httpx.HTTPStatusError as e:
            status_code = e.response.status_code
            response_text = e.response.text[:1000].replace("\n", " ")
            if status_code == 401:
                logger.error(
                    "OpenRouter rejected the configured API key while querying %s. "
                    "Check OPENROUTER_API_KEY and restart the backend.",
                    model,
                )
            elif status_code == 402:
                logger.error(
                    "OpenRouter returned 402 Payment Required while querying %s. "
                    "Add credits or enable billing for the OpenRouter account/key.",
                    model,
                )
            elif status_code == 404:
                logger.error(
                    "OpenRouter could not find or route model %s. Pick another model from the refreshed catalog. "
                    "Response: %s",
                    model,
                    response_text,
                )
            elif status_code == 400:
                logger.error(
                    "OpenRouter rejected the request for model %s. Response: %s",
                    model,
                    response_text,
                )
            else:
                logger.error(
                    "OpenRouter HTTP %s querying model %s. Response: %s",
                    status_code,
                    model,
                    response_text,
                )
            mark_span_error(span, e)
            span.set_output({"error": str(e), "status_code": status_code, "response": response_text})
            return None
        except Exception as e:
            logger.exception("Error querying model %s", model)
            mark_span_error(span, e)
            span.set_output({"error": str(e)})
            return None


@tracer.chain(name="openrouter.query_models_parallel")
async def query_models_parallel(
    models: List[str],
    messages: List[Dict[str, str]]
) -> Dict[str, Optional[Dict[str, Any]]]:
    """
    Query multiple models in parallel.

    Args:
        models: List of OpenRouter model identifiers
        messages: List of message dicts to send to each model

    Returns:
        Dict mapping model identifier to response dict (or None if failed)
    """
    import asyncio

    if not _is_configured_api_key(OPENROUTER_API_KEY):
        logger.error("OpenRouter API key is not configured. Skipping %s model request(s).", len(models))
        return {model: None for model in models}

    apply_context_to_current_span(
        llm_parallel_model_count=len(models),
        llm_parallel_models=models,
        llm_message_count=len(messages),
        llm_prompt_characters=sum(len(message.get("content", "")) for message in messages),
    )

    # Create tasks for all models
    tasks = [query_model(model, messages) for model in models]

    # Wait for all to complete
    responses = await asyncio.gather(*tasks)

    # Map models to their responses
    return {model: response for model, response in zip(models, responses)}
