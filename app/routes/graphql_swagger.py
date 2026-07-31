"""Auto-register Swagger-documented REST wrappers for each root GraphQL operation."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Request, Response
from graphql import (
    GraphQLEnumType,
    GraphQLInputObjectType,
    GraphQLList,
    GraphQLNonNull,
    GraphQLObjectType,
    GraphQLScalarType,
    GraphQLSchema,
)
from graphql.type.definition import GraphQLArgument, GraphQLField
from pydantic import BaseModel, Field
from strawberry.schema import Schema as StrawberrySchema

from app.core.deps import get_graphql_context
from app.core.logging import get_logger

logger = get_logger(__name__)

_SELECTION_DEPTH = 2


class GraphQLVariablesBody(BaseModel):
    """Variables for the GraphQL operation (keys match the GraphQL argument names)."""

    variables: dict[str, Any] = Field(default_factory=dict)


def _unwrap_graphql_type(type_) -> GraphQLScalarType | GraphQLEnumType | GraphQLObjectType | GraphQLInputObjectType:
    while isinstance(type_, (GraphQLNonNull, GraphQLList)):
        type_ = type_.of_type
    return type_


def _graphql_type_string(type_) -> str:
    if isinstance(type_, GraphQLNonNull):
        return f"{_graphql_type_string(type_.of_type)}!"
    if isinstance(type_, GraphQLList):
        return f"[{_graphql_type_string(type_.of_type)}]"
    return type_.name


def _example_value_for_type(type_) -> Any:
    type_ = _unwrap_graphql_type(type_)
    if isinstance(type_, GraphQLList):
        return []
    name = getattr(type_, "name", "")
    if name in {"String", "ID"}:
        return ""
    if name == "Int":
        return 0
    if name == "Float":
        return 0.0
    if name == "Boolean":
        return False
    if isinstance(type_, GraphQLEnumType):
        values = list(type_.values.keys())
        return values[0] if values else None
    return None


def _build_variables_example(args: dict[str, GraphQLArgument]) -> dict[str, Any]:
    return {name: _example_value_for_type(arg.type) for name, arg in args.items()}


def _build_selection_set(type_, *, depth: int = _SELECTION_DEPTH, current_depth: int = 0) -> str:
    type_ = _unwrap_graphql_type(type_)
    if isinstance(type_, (GraphQLScalarType, GraphQLEnumType)):
        return ""
    if not isinstance(type_, GraphQLObjectType):
        return ""
    if current_depth >= depth:
        return "{ __typename }"

    parts: list[str] = []
    for field_name, field in type_.fields.items():
        inner = _unwrap_graphql_type(field.type)
        if isinstance(inner, (GraphQLScalarType, GraphQLEnumType)):
            parts.append(field_name)
        elif isinstance(inner, GraphQLObjectType):
            nested = _build_selection_set(field.type, depth=depth, current_depth=current_depth + 1)
            if nested:
                parts.append(f"{field_name} {nested}")

    if not parts:
        return "{ __typename }"
    return "{" + " ".join(parts) + "}"


def _build_operation_document(*, operation_kind: str, field_name: str, field: GraphQLField) -> str:
    arg_names = list(field.args.keys())
    var_defs = [f"${name}: {_graphql_type_string(field.args[name].type)}" for name in arg_names]
    call_args = [f"{name}: ${name}" for name in arg_names]
    selection = _build_selection_set(field.type)

    signature = f"({', '.join(var_defs)})" if var_defs else ""
    call = f"({', '.join(call_args)})" if call_args else ""
    return f"{operation_kind} GraphQLSwaggerOp{signature} {{ {field_name}{call} {selection} }}"


def _tag_for_operation(field_name: str, operation_kind: str) -> str:
    name = field_name
    lowered = name.lower()

    if lowered in {"portallogin", "portalrefreshtoken", "portallogout"}:
        return "graphql-portal-auth"
    if lowered in {"login", "logout", "refreshtoken", "verifytotp", "enabletotp", "confirmtotp", "disabletotp"}:
        return "graphql-auth"
    if lowered.startswith("portal"):
        return "graphql-portal"
    if "company" in lowered or lowered == "companies":
        return "graphql-companies"
    if "contact" in lowered:
        return "graphql-contacts"
    if "tag" in lowered:
        return "graphql-tags"
    if "project" in lowered:
        return "graphql-projects"
    if any(k in lowered for k in ("phase", "milestone", "task", "workload", "dependency", "reorder")):
        return "graphql-planning"
    if any(k in lowered for k in ("approval", "readyforreview", "milestonechanges")) or lowered.startswith(
        ("approve", "request", "mark")
    ):
        return "graphql-approvals"
    if any(k in lowered for k in ("document", "upload")):
        return "graphql-documents"
    if lowered == "status":
        return "graphql-system"
    return f"graphql-{operation_kind}s"


async def _execute_graphql_operation(
    *,
    strawberry_schema: StrawberrySchema,
    request: Request,
    response: Response,
    operation_kind: str,
    field_name: str,
    field: GraphQLField,
    variables: dict[str, Any],
) -> dict[str, Any]:
    document = _build_operation_document(
        operation_kind=operation_kind,
        field_name=field_name,
        field=field,
    )
    async for context in get_graphql_context(request, response):
        result = await strawberry_schema.execute(
            document,
            variable_values=variables or None,
            context_value=context,
        )
        if result.errors:
            return {
                "data": result.data,
                "errors": [{"message": err.message, "extensions": err.extensions} for err in result.errors],
            }
        return {"data": result.data}
    return {"data": None, "errors": [{"message": "No GraphQL context available"}]}


def _make_handler(
    strawberry_schema: StrawberrySchema,
    operation_kind: str,
    field_name: str,
    field: GraphQLField,
):
    variables_example = _build_variables_example(field.args)

    async def handler(
        request: Request,
        response: Response,
        body: GraphQLVariablesBody = Body(
            ...,
            json_schema_extra={"example": {"variables": variables_example}},
        ),
    ) -> dict[str, Any]:
        return await _execute_graphql_operation(
            strawberry_schema=strawberry_schema,
            request=request,
            response=response,
            operation_kind=operation_kind,
            field_name=field_name,
            field=field,
            variables=body.variables,
        )

    return handler


def register_graphql_swagger_routes(app_router: APIRouter, strawberry_schema: StrawberrySchema) -> int:
    """Register one POST route per root GraphQL query/mutation. Returns count registered."""
    graphql_schema: GraphQLSchema = strawberry_schema._schema
    registered = 0

    groups: list[tuple[str, GraphQLObjectType | None]] = [
        ("query", graphql_schema.query_type),
        ("mutation", graphql_schema.mutation_type),
    ]

    for operation_kind, root_type in groups:
        if root_type is None:
            continue
        path_segment = "queries" if operation_kind == "query" else "mutations"
        for field_name, field in root_type.fields.items():
            path = f"/graphql/{path_segment}/{field_name}"
            tag = _tag_for_operation(field_name, operation_kind)
            summary = f"GraphQL {operation_kind}: {field_name}"
            description = (
                f"Swagger wrapper for the `{field_name}` GraphQL {operation_kind}. "
                f"Executes the same logic as `POST /graphql`. "
                f"Pass GraphQL arguments inside the `variables` object. "
                f"Use `Authorization: Bearer <token>` when the operation requires auth."
            )
            app_router.add_api_route(
                path,
                _make_handler(strawberry_schema, operation_kind, field_name, field),
                methods=["POST"],
                tags=[tag],
                summary=summary,
                description=description,
                name=f"graphql_{operation_kind}_{field_name}",
            )
            registered += 1

    logger.info("Registered GraphQL Swagger routes", extra={"extra_data": {"count": registered}})
    return registered


def create_graphql_swagger_router(strawberry_schema: StrawberrySchema) -> APIRouter:
    router = APIRouter()
    register_graphql_swagger_routes(router, strawberry_schema)
    return router
