from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import strawberry
from strawberry.types import Info

from sqlalchemy import func, select

from app.core.deps import require_authenticated
from app.db.enums import EnrollmentStatus, TouchpointStatus
from app.db.models.organization import Organization
from app.db.models.retention import RetentionEnrollment, Touchpoint
from app.graphql.companies.schema import CompanyType, company_from_model
from app.graphql.health.service import get_at_risk_companies, get_company_health_history
from app.graphql.org_settings import health_settings_from_dict
from app.graphql.retention.schema import RetentionEnrollmentType

# Touchpoint signals disabled for at-risk reasons — restore when needed.
# NO_RECENT_CONTACT_DAYS = 90


@strawberry.type
class AtRiskCompanyType:
    company: CompanyType
    _company_id: strawberry.Private[UUID]

    async def _overdue_touchpoint_count(self, db) -> int:
        result = await db.execute(
            select(func.count())
            .select_from(Touchpoint)
            .where(
                Touchpoint.company_id == self._company_id,
                Touchpoint.status == TouchpointStatus.SCHEDULED.value,
                Touchpoint.scheduled_at < datetime.now(UTC),
            )
        )
        return int(result.scalar_one())

    async def _last_touchpoint_at(self, db) -> datetime | None:
        result = await db.execute(
            select(func.max(Touchpoint.completed_at)).where(
                Touchpoint.company_id == self._company_id,
                Touchpoint.completed_at.is_not(None),
            )
        )
        return result.scalar_one()

    @strawberry.field
    async def reasons(self, info: Info) -> list[str]:
        ctx = require_authenticated(info.context)
        reasons = ["LOW_HEALTH_SCORE"]

        # if await self._overdue_touchpoint_count(ctx.db) > 0:
        #     reasons.append("OVERDUE_TOUCHPOINTS")

        # last_at = await self._last_touchpoint_at(ctx.db)
        # cutoff = datetime.now(UTC) - timedelta(days=NO_RECENT_CONTACT_DAYS)
        # if last_at is None or last_at < cutoff:
        #     reasons.append("NO_RECENT_CONTACT")

        return reasons

    @strawberry.field
    async def last_touchpoint_at(self, info: Info) -> datetime | None:
        ctx = require_authenticated(info.context)
        return await self._last_touchpoint_at(ctx.db)

    @strawberry.field
    async def overdue_touchpoint_count(self, info: Info) -> int:
        ctx = require_authenticated(info.context)
        return await self._overdue_touchpoint_count(ctx.db)

    @strawberry.field
    async def active_enrollments(self, info: Info) -> list[RetentionEnrollmentType]:
        ctx = require_authenticated(info.context)
        result = await ctx.db.execute(
            select(RetentionEnrollment).where(
                RetentionEnrollment.company_id == self._company_id,
                RetentionEnrollment.status == EnrollmentStatus.ACTIVE.value,
            )
        )
        return [RetentionEnrollmentType.from_model(row) for row in result.scalars().all()]


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
    async def at_risk_companies(self, info: Info, threshold: float | None = None) -> list[AtRiskCompanyType]:
        ctx = require_authenticated(info.context)
        org = await ctx.db.get(Organization, ctx.user.org_id)
        settings = health_settings_from_dict(org.settings if org else {})
        rows = await get_at_risk_companies(ctx.db, threshold=threshold, org_settings=settings)
        return [
            AtRiskCompanyType(company=company_from_model(r), _company_id=r.id)
            for r in rows
        ]

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
