"""Phoenix observability helpers for LLM Council.

Tracing is intentionally optional. It is enabled when either:
- PHOENIX_ENABLED is set to a truthy value, or
- PHOENIX_COLLECTOR_ENDPOINT is configured.

When tracing is disabled, the helpers in this module degrade to no-op
decorators and spans so the rest of the application does not need to care.
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

logger = logging.getLogger(__name__)

_TRUTHY_VALUES = {"1", "true", "yes", "on"}
_TRACE_CONTEXT: ContextVar[dict[str, Any]] = ContextVar("trace_context", default={})


class _NoOpSpan:
    """No-op span used when Phoenix tracing is disabled."""

    def __enter__(self) -> "_NoOpSpan":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def set_input(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def set_output(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def set_tool(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def set_attribute(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def set_attributes(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def set_status(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def record_exception(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def _identity_decorator(func=None, **_kwargs):
    if func is None:
        def decorator(target):
            return target
        return decorator
    return func


class _NoOpTracer:
    """No-op tracer used when Phoenix tracing is disabled."""

    def start_as_current_span(self, *_args: Any, **_kwargs: Any) -> _NoOpSpan:
        return _NoOpSpan()

    def chain(self, func=None, **kwargs):
        return _identity_decorator(func, **kwargs)

    def tool(self, func=None, **kwargs):
        return _identity_decorator(func, **kwargs)

    def agent(self, func=None, **kwargs):
        return _identity_decorator(func, **kwargs)

    def llm(self, func=None, **kwargs):
        return _identity_decorator(func, **kwargs)


_NOOP_TRACER = _NoOpTracer()
_TRACER_PROVIDER = None
_STATUS = None
_STATUS_CODE = None
_TRACE_API = None
_TRACING_ENABLED = False


def _should_enable_tracing() -> bool:
    explicit_flag = os.getenv("PHOENIX_ENABLED")
    if explicit_flag is not None:
        return explicit_flag.strip().lower() in _TRUTHY_VALUES
    return bool(os.getenv("PHOENIX_COLLECTOR_ENDPOINT"))


if _should_enable_tracing():
    try:
        from opentelemetry import trace as trace_api
        from opentelemetry.trace import Status, StatusCode
        from phoenix.otel import register

        _TRACER_PROVIDER = register(
            project_name=os.getenv("PHOENIX_PROJECT_NAME", "llm-council"),
            batch=True,
            auto_instrument=False,
            verbose=False,
        )
        _STATUS = Status
        _STATUS_CODE = StatusCode
        _TRACE_API = trace_api
        _TRACING_ENABLED = True
        logger.info("Phoenix tracing enabled for project '%s'", os.getenv("PHOENIX_PROJECT_NAME", "llm-council"))
    except Exception as exc:  # pragma: no cover - defensive setup guard
        logger.warning("Phoenix tracing disabled due to setup failure: %s", exc)


def get_tracer(name: str):
    """Return a Phoenix/OpenInference tracer or a no-op tracer."""
    if _TRACING_ENABLED and _TRACER_PROVIDER is not None:
        return _TRACER_PROVIDER.get_tracer(name)
    return _NOOP_TRACER


def is_tracing_enabled() -> bool:
    """Return whether Phoenix tracing is active for this process."""
    return _TRACING_ENABLED


def _serialize_attribute_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        if all(isinstance(item, (bool, int, float, str)) for item in value):
            return list(value)
        return json.dumps(value, default=str)
    if isinstance(value, dict):
        return json.dumps(value, default=str)
    return str(value)


def set_span_attributes(span: Any, **attrs: Any) -> None:
    """Set a batch of attributes on a span, serializing complex values safely."""
    for key, value in attrs.items():
        serialized = _serialize_attribute_value(value)
        if serialized is not None:
            span.set_attribute(key, serialized)


def annotate_current_span(**attrs: Any) -> None:
    """Set attributes on the current span if tracing is active and a span exists."""
    if _TRACE_API is None:
        return
    span = _TRACE_API.get_current_span()
    span_context = span.get_span_context()
    if not span_context or not span_context.is_valid:
        return
    set_span_attributes(span, **attrs)


def get_trace_context() -> dict[str, Any]:
    """Return the current request-scoped trace context metadata."""
    return dict(_TRACE_CONTEXT.get())


@contextmanager
def using_trace_context(**attrs: Any):
    """Attach request-scoped metadata that child spans can reuse.

    This is independent of Phoenix/OpenTelemetry and is safe when tracing is off.
    """
    current = dict(_TRACE_CONTEXT.get())
    current.update({key: value for key, value in attrs.items() if value is not None})
    token = _TRACE_CONTEXT.set(current)
    try:
        yield current
    finally:
        _TRACE_CONTEXT.reset(token)


def apply_context_to_current_span(**extra_attrs: Any) -> None:
    """Apply request-scoped context and any extra attrs to the current span."""
    context_attrs = get_trace_context()
    context_attrs.update({key: value for key, value in extra_attrs.items() if value is not None})
    annotate_current_span(**context_attrs)


def get_current_trace_payload() -> dict[str, Any]:
    """Return the current trace identifiers and optional viewer URL."""
    payload: dict[str, Any] = {
        "enabled": _TRACING_ENABLED,
        "project_name": os.getenv("PHOENIX_PROJECT_NAME", "llm-council"),
    }

    if _TRACE_API is None:
        return payload

    span = _TRACE_API.get_current_span()
    span_context = span.get_span_context()
    if not span_context or not span_context.is_valid:
        return payload

    trace_id = format(span_context.trace_id, "032x")
    span_id = format(span_context.span_id, "016x")
    payload["trace_id"] = trace_id
    payload["span_id"] = span_id

    viewer_template = os.getenv("PHOENIX_TRACE_URL_TEMPLATE")
    if viewer_template:
        payload["viewer_url"] = viewer_template.format(
            trace_id=trace_id,
            span_id=span_id,
            project_name=payload["project_name"],
        )

    return payload


def mark_span_ok(span: Any) -> None:
    """Mark a span as successful when Phoenix tracing is enabled."""
    if _STATUS is not None and _STATUS_CODE is not None:
        span.set_status(_STATUS(_STATUS_CODE.OK))


def mark_span_error(span: Any, error: Exception) -> None:
    """Record an exception and mark the span as failed."""
    span.record_exception(error)
    if _STATUS is not None and _STATUS_CODE is not None:
        span.set_status(_STATUS(_STATUS_CODE.ERROR))