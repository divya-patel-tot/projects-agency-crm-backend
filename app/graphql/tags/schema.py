from __future__ import annotations

from uuid import UUID

import strawberry
from strawberry.types import Info

from app.core.deps import require_authenticated, require_role
from app.core.exceptions import DomainError, NotFoundError
from app.db.models.tag import EntityTag, Tag
from app.graphql.loaders import (
    add_entity_tag,
    create_tag,
    list_tags,
    remove_entity_tag,
    validate_entity_type,
)


@strawberry.type
class TagType:
    id: strawberry.ID
    name: str


@strawberry.type
class TagQuery:
    @strawberry.field
    async def tags(self, info: Info) -> list[TagType]:
        ctx = require_authenticated(info.context)
        rows = await list_tags(ctx.db)
        return [TagType(id=strawberry.ID(str(r.id)), name=r.name) for r in rows]


@strawberry.type
class TagMutation:
    @strawberry.mutation
    async def create_tag(self, info: Info, name: str) -> TagType:
        ctx = require_role(info.context, "admin", "project_manager")
        tag = Tag(org_id=ctx.user.org_id, name=name.strip())
        row = await create_tag(ctx.db, tag)
        return TagType(id=strawberry.ID(str(row.id)), name=row.name)

    @strawberry.mutation
    async def add_tag(
        self,
        info: Info,
        entity_type: str,
        entity_id: strawberry.ID,
        tag_id: strawberry.ID,
    ) -> bool:
        ctx = require_role(info.context, "admin", "project_manager")
        try:
            et = validate_entity_type(entity_type)
        except ValueError as exc:
            raise DomainError(str(exc)) from exc
        row = EntityTag(
            org_id=ctx.user.org_id,
            entity_type=et,
            entity_id=UUID(str(entity_id)),
            tag_id=UUID(str(tag_id)),
        )
        await add_entity_tag(ctx.db, row)
        return True

    @strawberry.mutation
    async def remove_tag(
        self,
        info: Info,
        entity_type: str,
        entity_id: strawberry.ID,
        tag_id: strawberry.ID,
    ) -> bool:
        ctx = require_role(info.context, "admin", "project_manager")
        try:
            et = validate_entity_type(entity_type)
        except ValueError as exc:
            raise DomainError(str(exc)) from exc
        await remove_entity_tag(ctx.db, ctx.user.org_id, et, UUID(str(entity_id)), UUID(str(tag_id)))
        return True
