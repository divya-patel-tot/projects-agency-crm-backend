from uuid import UUID

import strawberry
from strawberry.types import Info

from app.core.deps import require_authenticated
from app.graphql.contacts.service import (
    create_contact_record,
    delete_contact_record,
    get_contact_by_id,
    get_contacts,
    update_contact_record,
)


@strawberry.type
class ContactType:
    id: strawberry.ID
    company_id: strawberry.ID
    first_name: str
    last_name: str
    email: str | None = None
    phone: str | None = None
    title: str | None = None
    department: str | None = None
    is_primary: bool
    preferred_channel: str | None = None
    timezone: str | None = None
    portal_access_enabled: bool
    linkedin_url: str | None = None
    status: str

    @classmethod
    def from_model(cls, contact) -> "ContactType":
        return cls(
            id=strawberry.ID(str(contact.id)),
            company_id=strawberry.ID(str(contact.company_id)),
            first_name=contact.first_name,
            last_name=contact.last_name,
            email=contact.email,
            phone=contact.phone,
            title=contact.title,
            department=contact.department,
            is_primary=contact.is_primary,
            preferred_channel=contact.preferred_channel,
            timezone=contact.timezone,
            portal_access_enabled=contact.portal_access_enabled,
            linkedin_url=contact.linkedin_url,
            status=contact.status,
        )


@strawberry.type
class ContactQuery:
    @strawberry.field
    async def contacts(self, info: Info) -> list[ContactType]:
        ctx = require_authenticated(info.context)
        rows = await get_contacts(ctx.db)
        return [ContactType.from_model(row) for row in rows]

    @strawberry.field
    async def contact(self, info: Info, id: strawberry.ID) -> ContactType | None:
        ctx = require_authenticated(info.context)
        try:
            row = await get_contact_by_id(ctx.db, UUID(str(id)))
        except Exception:
            return None
        return ContactType.from_model(row)


@strawberry.type
class ContactMutation:
    @strawberry.mutation
    async def create_contact(
        self,
        info: Info,
        company_id: strawberry.ID,
        first_name: str,
        last_name: str,
        email: str | None = None,
        phone: str | None = None,
        title: str | None = None,
        department: str | None = None,
        is_primary: bool = False,
        preferred_channel: str | None = None,
        timezone: str | None = None,
        portal_access_enabled: bool = False,
        linkedin_url: str | None = None,
        status: str = "active",
    ) -> ContactType:
        ctx = require_authenticated(info.context)
        row = await create_contact_record(
            ctx.db,
            actor=ctx.user,
            company_id=UUID(str(company_id)),
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=phone,
            title=title,
            department=department,
            is_primary=is_primary,
            preferred_channel=preferred_channel,
            timezone=timezone,
            portal_access_enabled=portal_access_enabled,
            linkedin_url=linkedin_url,
            status=status,
        )
        return ContactType.from_model(row)

    @strawberry.mutation
    async def update_contact(
        self,
        info: Info,
        id: strawberry.ID,
        first_name: str | None = None,
        last_name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        title: str | None = None,
        department: str | None = None,
        is_primary: bool | None = None,
        preferred_channel: str | None = None,
        timezone: str | None = None,
        portal_access_enabled: bool | None = None,
        linkedin_url: str | None = None,
        status: str | None = None,
    ) -> ContactType:
        ctx = require_authenticated(info.context)
        updates = {
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
            "phone": phone,
            "title": title,
            "department": department,
            "is_primary": is_primary,
            "preferred_channel": preferred_channel,
            "timezone": timezone,
            "portal_access_enabled": portal_access_enabled,
            "linkedin_url": linkedin_url,
            "status": status,
        }
        row = await update_contact_record(
            ctx.db,
            actor=ctx.user,
            contact_id=UUID(str(id)),
            updates=updates,
        )
        return ContactType.from_model(row)

    @strawberry.mutation
    async def delete_contact(self, info: Info, id: strawberry.ID) -> bool:
        ctx = require_authenticated(info.context)
        await delete_contact_record(ctx.db, actor=ctx.user, contact_id=UUID(str(id)))
        return True
