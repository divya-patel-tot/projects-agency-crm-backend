import strawberry
from strawberry.types import Info

from app.core.deps import GraphQLContext
from app.db.models.company import Company


@strawberry.type
class OrganizationViewerType:
    id: strawberry.ID
    name: str
    plan: str | None = None
    logo_url: str | None = None


@strawberry.type
class CompanyViewerType:
    id: strawberry.ID
    name: str
    logo_url: str | None = None
    status: str


@strawberry.type
class ContactViewerType:
    id: strawberry.ID
    first_name: str
    last_name: str
    title: str | None = None
    is_primary: bool = False


@strawberry.type
class ViewerType:
    id: strawberry.ID
    name: str
    email: str
    role: str | None = None
    status: str
    avatar_url: str | None = None
    scope: str
    totp_enabled: bool = False
    organization: OrganizationViewerType | None = None
    company: CompanyViewerType | None = None
    contact: ContactViewerType | None = None


def _organization_viewer(org) -> OrganizationViewerType:
    return OrganizationViewerType(
        id=strawberry.ID(str(org.id)),
        name=org.name,
        plan=org.plan,
    )


@strawberry.type
class ViewerQuery:
    @strawberry.field(description="Signed-in internal user or portal contact.")
    async def me(self, info: Info) -> ViewerType | None:
        ctx: GraphQLContext = info.context

        if ctx.user is not None and ctx.org is not None:
            return ViewerType(
                id=strawberry.ID(str(ctx.user.id)),
                name=ctx.user.name,
                email=ctx.user.email,
                role=ctx.user.role,
                status=ctx.user.status,
                avatar_url=ctx.user.avatar_url,
                scope="INTERNAL",
                totp_enabled=ctx.user.totp_enabled,
                organization=_organization_viewer(ctx.org),
            )

        if ctx.contact is not None and ctx.org is not None and ctx.company_id is not None and ctx.db is not None:
            company = await ctx.db.get(Company, ctx.company_id)
            company_view = None
            if company is not None:
                company_view = CompanyViewerType(
                    id=strawberry.ID(str(company.id)),
                    name=company.name,
                    logo_url=company.logo_url,
                    status=company.status,
                )
            display_name = f"{ctx.contact.first_name} {ctx.contact.last_name}".strip()
            return ViewerType(
                id=strawberry.ID(str(ctx.contact.id)),
                name=display_name or ctx.contact.email or "Portal user",
                email=ctx.contact.email or "",
                status=ctx.contact.status,
                scope="PORTAL",
                organization=_organization_viewer(ctx.org),
                company=company_view,
                contact=ContactViewerType(
                    id=strawberry.ID(str(ctx.contact.id)),
                    first_name=ctx.contact.first_name,
                    last_name=ctx.contact.last_name,
                    title=ctx.contact.title,
                    is_primary=ctx.contact.is_primary,
                ),
            )

        return None
