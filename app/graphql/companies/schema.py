from uuid import UUID

import strawberry
from sqlalchemy import func, select
from strawberry.types import Info

from app.core.deps import GraphQLContext, require_authenticated, require_role
from app.db.models.contact import Contact
from app.db.models.project import Project
from app.db.models.user import User
from app.graphql.companies.service import (
    create_company_record,
    delete_company_record,
    get_companies,
    get_company_by_id,
    update_company_record,
)
from app.graphql.contacts.schema import ContactType
from app.graphql.loaders import get_contacts_by_company_loader
from app.graphql.users.schema import UserSummaryType


@strawberry.type
class CompanyType:
    id: strawberry.ID
    name: str
    industry: str | None = None
    website: str | None = None
    logo_url: str | None = None
    status: str
    account_owner_id: strawberry.ID | None = None
    health_score: float | None = None

    @strawberry.field
    async def contacts(self, info: Info) -> list[ContactType]:
        loader = get_contacts_by_company_loader(info.context)
        rows = await loader.load(UUID(str(self.id)))
        return [ContactType.from_model(row) for row in rows]

    @strawberry.field
    async def account_owner(self, info: Info) -> UserSummaryType | None:
        if self.account_owner_id is None or info.context.db is None:
            return None
        user = await info.context.db.get(User, UUID(str(self.account_owner_id)))
        if user is None or user.deleted_at is not None:
            return None
        return UserSummaryType.from_model(user)

    @strawberry.field
    async def primary_contact(self, info: Info) -> ContactType | None:
        contacts = await self.contacts(info)
        if not contacts:
            return None
        primary = next((c for c in contacts if c.is_primary), None)
        return primary or contacts[0]

    @strawberry.field
    async def contact_count(self, info: Info) -> int:
        if info.context.db is None:
            return 0
        result = await info.context.db.execute(
            select(func.count())
            .select_from(Contact)
            .where(Contact.company_id == UUID(str(self.id)), Contact.deleted_at.is_(None))
        )
        return int(result.scalar_one())

    @strawberry.field
    async def project_count(self, info: Info) -> int:
        if info.context.db is None:
            return 0
        result = await info.context.db.execute(
            select(func.count())
            .select_from(Project)
            .where(Project.company_id == UUID(str(self.id)), Project.deleted_at.is_(None))
        )
        return int(result.scalar_one())


def company_from_model(company) -> CompanyType:
    return CompanyType(
        id=strawberry.ID(str(company.id)),
        name=company.name,
        industry=company.industry,
        website=company.website,
        logo_url=company.logo_url,
        status=company.status,
        account_owner_id=strawberry.ID(str(company.account_owner_id)) if company.account_owner_id else None,
        health_score=float(company.health_score) if company.health_score is not None else None,
    )


@strawberry.type
class CompanyQuery:
    @strawberry.field
    async def companies(self, info: Info) -> list[CompanyType]:
        ctx = require_authenticated(info.context)
        rows = await get_companies(ctx.db)
        return [company_from_model(row) for row in rows]

    @strawberry.field
    async def company(self, info: Info, id: strawberry.ID) -> CompanyType | None:
        ctx = require_authenticated(info.context)
        try:
            row = await get_company_by_id(ctx.db, UUID(str(id)))
        except Exception:
            return None
        return company_from_model(row)


@strawberry.type
class CompanyMutation:
    @strawberry.mutation
    async def create_company(
        self,
        info: Info,
        name: str,
        industry: str | None = None,
        website: str | None = None,
        logo_url: str | None = None,
        status: str = "lead",
        account_owner_id: strawberry.ID | None = None,
        health_score: float | None = None,
    ) -> CompanyType:
        ctx = require_role(info.context, "admin", "account_manager")
        row = await create_company_record(
            ctx.db,
            actor=ctx.user,
            name=name,
            industry=industry,
            website=website,
            logo_url=logo_url,
            status=status,
            account_owner_id=UUID(str(account_owner_id)) if account_owner_id else None,
            health_score=health_score,
        )
        return company_from_model(row)

    @strawberry.mutation
    async def update_company(
        self,
        info: Info,
        id: strawberry.ID,
        name: str | None = None,
        industry: str | None = None,
        website: str | None = None,
        logo_url: str | None = None,
        status: str | None = None,
        account_owner_id: strawberry.ID | None = None,
        health_score: float | None = None,
    ) -> CompanyType:
        ctx = require_role(info.context, "admin", "account_manager")
        updates = {
            "name": name,
            "industry": industry,
            "website": website,
            "logo_url": logo_url,
            "status": status,
            "account_owner_id": UUID(str(account_owner_id)) if account_owner_id else None,
            "health_score": health_score,
        }
        row = await update_company_record(ctx.db, actor=ctx.user, company_id=UUID(str(id)), updates=updates)
        return company_from_model(row)

    @strawberry.mutation
    async def delete_company(self, info: Info, id: strawberry.ID) -> bool:
        ctx = require_role(info.context, "admin", "account_manager")
        await delete_company_record(ctx.db, actor=ctx.user, company_id=UUID(str(id)))
        return True
