"""Structured logging for GraphQL operations (auth context, duration, errors)."""

from __future__ import annotations

import time
from typing import Any

from strawberry.extensions import SchemaExtension

from app.core.deps import GraphQLContext
from app.core.logging import get_logger

logger = get_logger("graphql.request")


def _actor_fields(context: Any) -> dict[str, str | None]:
    if not isinstance(context, GraphQLContext):
        return {
            "authenticated": False,
            "actor_type": None,
            "user_id": None,
            "org_id": None,
            "contact_id": None,
            "company_id": None,
            "role": None,
        }

    user = context.user
    contact = context.contact
    org = context.org
    return {
        "authenticated": user is not None or contact is not None,
        "actor_type": context.actor_type.value if context.actor_type else None,
        "user_id": str(user.id) if user else None,
        "org_id": str(org.id) if org else None,
        "contact_id": str(contact.id) if contact else None,
        "company_id": str(context.company_id) if context.company_id else None,
        "role": user.role if user else None,
    }


def _safe_operation_meta(execution_context: Any) -> tuple[str, str | None]:
    """Strawberry raises if the request has no parseable GraphQL document."""
    operation_name = "(anonymous)"
    operation_type: str | None = None
    try:
        operation_name = execution_context.operation_name or "(anonymous)"
    except RuntimeError:
        pass
    try:
        op_type = execution_context.operation_type
        operation_type = op_type.value if op_type else None
    except RuntimeError:
        pass
    return operation_name, operation_type


class GraphQLRequestLoggingExtension(SchemaExtension):
    """Logs each GraphQL operation with timing and redacted auth context."""

    def on_operation(self):
        start = time.perf_counter()
        ctx = self.execution_context
        operation_name, operation_type = _safe_operation_meta(ctx)
        path = getattr(getattr(ctx, "context", None), "request", None)
        request_path = path.url.path if path is not None else "/graphql"

        yield

        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        result = ctx.result
        errors: list[str] = []
        if result and getattr(result, "errors", None):
            errors = [str(error.message) for error in result.errors if error is not None]

        extra: dict[str, Any] = {
            "path": request_path,
            "operation": operation_name,
            "operation_type": operation_type,
            "duration_ms": duration_ms,
            **_actor_fields(ctx.context),
        }
        if errors:
            extra["errors"] = errors
            logger.warning("GraphQL operation completed with errors", extra={"extra_data": extra})
        else:
            logger.info("GraphQL operation", extra={"extra_data": extra})
