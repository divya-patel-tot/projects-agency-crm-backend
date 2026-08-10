from __future__ import annotations

import strawberry
from strawberry.types import Info

from app.core.deps import require_authenticated
from app.graphql.loaders import list_company_sizes, list_industries


@strawberry.type
class CompanySizeType:
    id: strawberry.ID
    label: str


@strawberry.type
class IndustryType:
    id: strawberry.ID
    name: str


@strawberry.type
class LookupQuery:
    @strawberry.field
    async def company_sizes(self, info: Info) -> list[CompanySizeType]:
        ctx = require_authenticated(info.context)
        rows = await list_company_sizes(ctx.db)
        return [CompanySizeType(id=strawberry.ID(str(r.id)), label=r.label) for r in rows]

    @strawberry.field
    async def industries(self, info: Info) -> list[IndustryType]:
        ctx = require_authenticated(info.context)
        rows = await list_industries(ctx.db)
        return [IndustryType(id=strawberry.ID(str(r.id)), name=r.name) for r in rows]
