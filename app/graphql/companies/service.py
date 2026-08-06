from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_activity_log
from app.core.exceptions import NotFoundError
from app.db.enums import UserRole
from app.db.models.company import Company
from app.db.models.user import User
from app.graphql.companies.repository import (
    create_company,
    get_company,
    list_companies,
    soft_delete_company,
)


def _company_to_dict(company: Company) -> dict:
    return {
        "id": str(company.id),
        "name": company.name,
        "industry": company.industry,
        "website": company.website,
        "status": company.status,
        "account_owner_id": str(company.account_owner_id) if company.account_owner_id else None,
        "health_score": float(company.health_score) if company.health_score is not None else None,
    }


async def get_companies(db: AsyncSession, *, actor: User | None = None) -> list[Company]:
    member_user_id = actor.id if actor is not None and actor.role == UserRole.TEAM_MEMBER.value else None
    return await list_companies(db, member_user_id)


async def get_company_by_id(db: AsyncSession, company_id: UUID, *, actor: User | None = None) -> Company:
    member_user_id = actor.id if actor is not None and actor.role == UserRole.TEAM_MEMBER.value else None
    company = await get_company(db, company_id, member_user_id)
    if company is None:
        raise NotFoundError("Company not found")
    return company


async def create_company_record(
    db: AsyncSession,
    *,
    actor: User,
    name: str,
    industry: str | None = None,
    website: str | None = None,
    logo_url: str | None = None,
    address: dict | None = None,
    size: str | None = None,
    timezone: str | None = None,
    status: str = "lead",
    account_owner_id: UUID | None = None,
    health_score: float | None = None,
) -> Company:
    company = Company(
        org_id=actor.org_id,
        name=name,
        industry=industry,
        website=website,
        logo_url=logo_url,
        address=address,
        size=size,
        timezone=timezone,
        status=status,
        account_owner_id=account_owner_id,
        health_score=health_score,
    )
    await create_company(db, company)
    await write_activity_log(
        db,
        org_id=actor.org_id,
        actor_id=actor.id,
        action="create",
        entity_type="company",
        entity_id=company.id,
        diff={"after": _company_to_dict(company)},
    )
    return company


async def update_company_record(
    db: AsyncSession,
    *,
    actor: User,
    company_id: UUID,
    updates: dict,
) -> Company:
    company = await get_company_by_id(db, company_id)
    before = _company_to_dict(company)
    for key, value in updates.items():
        if value is not None and hasattr(company, key):
            setattr(company, key, value)
    await db.flush()
    await write_activity_log(
        db,
        org_id=actor.org_id,
        actor_id=actor.id,
        action="update",
        entity_type="company",
        entity_id=company.id,
        diff={"before": before, "after": _company_to_dict(company)},
    )
    return company


async def delete_company_record(db: AsyncSession, *, actor: User, company_id: UUID) -> Company:
    company = await get_company_by_id(db, company_id)
    before = _company_to_dict(company)
    await soft_delete_company(db, company)
    await write_activity_log(
        db,
        org_id=actor.org_id,
        actor_id=actor.id,
        action="delete",
        entity_type="company",
        entity_id=company.id,
        diff={"before": before},
    )
    return company
