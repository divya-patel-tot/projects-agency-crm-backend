from datetime import datetime
from uuid import UUID

import strawberry
from strawberry.types import Info

from app.core.deps import require_authenticated
from app.graphql.companies.schema import CompanyType, company_from_model
from app.graphql.health.service import get_at_risk_companies, get_company_health_history
from app.graphql.org_settings import health_settings_from_dict
from app.db.models.organization import Organization


@strawberry.type
class HealthScoreType:
    id: strawberry.ID
    company_id: strawberry.ID
    score: float
    factors: strawberry.scalars.JSON
    ai_summary: str | None
    calculated_at: datetime

    @classmethod
    def from_model(cls, row) -> "HealthScoreType":
        return cls(
            id=strawberry.ID(str(row.id)),
            company_id=strawberry.ID(str(row.company_id)),
            score=float(row.score),
            factors=row.factors,
            ai_summary=row.ai_summary,
            calculated_at=row.calculated_at,
        )


@strawberry.type
class HealthQuery:
    @strawberry.field
    async def at_risk_companies(self, info: Info, threshold: float | None = None) -> list[CompanyType]:
        ctx = require_authenticated(info.context)
        org = await ctx.db.get(Organization, ctx.user.org_id)
        settings = health_settings_from_dict(org.settings if org else {})
        rows = await get_at_risk_companies(ctx.db, threshold=threshold, org_settings=settings)
        return [company_from_model(r) for r in rows]

    @strawberry.field
    async def health_score_history(
        self,
        info: Info,
        company_id: strawberry.ID,
        limit: int = 30,
    ) -> list[HealthScoreType]:
        ctx = require_authenticated(info.context)
        rows = await get_company_health_history(ctx.db, company_id=UUID(str(company_id)), limit=limit)
        return [HealthScoreType.from_model(r) for r in rows]
