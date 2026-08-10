from __future__ import annotations

import strawberry
from graphql import GraphQLError
from strawberry.types import Info

from app.core.deps import GraphQLContext, require_authenticated, require_portal
from app.core.exceptions import AuthenticationError, DomainError
from app.graphql.profile.preferences import normalize_preferences
from app.graphql.profile.service import (
    change_internal_password,
    change_portal_password,
    get_notification_preferences,
    update_internal_profile,
    update_notification_preferences,
    update_portal_profile,
)
from app.graphql.viewer.schema import CompanyViewerType, ContactViewerType, ViewerType, _organization_viewer


def _gql_error(exc: Exception) -> None:
    if isinstance(exc, (DomainError, AuthenticationError)):
        code = "authentication_error" if isinstance(exc, AuthenticationError) else exc.code
        raise GraphQLError(exc.message, extensions={"code": code}) from exc
    raise exc


@strawberry.type
class NotificationChannelType:
    email: bool
    in_app: bool


@strawberry.type
class NotificationPreferenceType:
    key: str
    email: bool
    in_app: bool


@strawberry.input
class NotificationChannelInput:
    email: bool
    in_app: bool


@strawberry.input
class NotificationPreferencesInput:
    change_requests: NotificationChannelInput | None = None
    task_assignments: NotificationChannelInput | None = None
    milestone_approvals: NotificationChannelInput | None = None
    retention_touchpoints: NotificationChannelInput | None = None
    project_updates: NotificationChannelInput | None = None


def _preferences_to_graphql(raw: dict[str, dict[str, bool]]) -> list[NotificationPreferenceType]:
    return [
        NotificationPreferenceType(key=key, email=row["email"], in_app=row["in_app"])
        for key, row in raw.items()
    ]


def _input_to_dict(data: NotificationPreferencesInput | None) -> dict[str, dict[str, bool]]:
    if data is None:
        return {}
    result: dict[str, dict[str, bool]] = {}
    for field in (
        "change_requests",
        "task_assignments",
        "milestone_approvals",
        "retention_touchpoints",
        "project_updates",
    ):
        row = getattr(data, field, None)
        if row is None:
            continue
        result[field] = {"email": row.email, "in_app": row.in_app}
    return result


@strawberry.type
class ProfileQuery:
    @strawberry.field
    async def my_notification_preferences(self, info: Info) -> list[NotificationPreferenceType]:
        ctx: GraphQLContext = info.context
        if ctx.user is not None:
            prefs = await get_notification_preferences(user=ctx.user)
            return _preferences_to_graphql(prefs)
        if ctx.contact is not None:
            prefs = await get_notification_preferences(contact=ctx.contact)
            return _preferences_to_graphql(prefs)
        raise GraphQLError("Authentication required", extensions={"code": "authentication_error"})


@strawberry.type
class ProfileMutation:
    @strawberry.mutation(description="Update the signed-in user's display profile.")
    async def update_my_profile(
        self,
        info: Info,
        name: str | None = None,
        avatar_url: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        title: str | None = None,
    ) -> ViewerType:
        ctx: GraphQLContext = info.context
        try:
            if ctx.user is not None and ctx.org is not None:
                require_authenticated(ctx)
                await update_internal_profile(
                    ctx.db,
                    user=ctx.user,
                    name=name,
                    avatar_url=avatar_url,
                )
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

            if ctx.contact is not None and ctx.org is not None:
                require_portal(ctx)
                await update_portal_profile(
                    ctx.db,
                    contact=ctx.contact,
                    first_name=first_name,
                    last_name=last_name,
                    title=title,
                )
                display_name = f"{ctx.contact.first_name} {ctx.contact.last_name}".strip()
                from app.db.models.company import Company

                company = await ctx.db.get(Company, ctx.company_id)
                company_view = None
                if company is not None:
                    company_view = CompanyViewerType(
                        id=strawberry.ID(str(company.id)),
                        name=company.name,
                        logo_url=company.logo_url,
                        status=company.status,
                    )
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

            raise GraphQLError("Authentication required", extensions={"code": "authentication_error"})
        except Exception as exc:
            _gql_error(exc)
            raise

    @strawberry.mutation(description="Change the signed-in user's password.")
    async def change_my_password(
        self,
        info: Info,
        current_password: str,
        new_password: str,
    ) -> bool:
        ctx: GraphQLContext = info.context
        try:
            if ctx.user is not None:
                require_authenticated(ctx)
                await change_internal_password(
                    ctx.db,
                    user=ctx.user,
                    current_password=current_password,
                    new_password=new_password,
                )
                return True

            if ctx.contact is not None:
                require_portal(ctx)
                await change_portal_password(
                    ctx.db,
                    contact=ctx.contact,
                    current_password=current_password,
                    new_password=new_password,
                )
                return True

            raise GraphQLError("Authentication required", extensions={"code": "authentication_error"})
        except Exception as exc:
            _gql_error(exc)
            raise

    @strawberry.mutation(description="Update notification channel preferences.")
    async def update_my_notification_preferences(
        self,
        info: Info,
        preferences: NotificationPreferencesInput,
    ) -> list[NotificationPreferenceType]:
        ctx: GraphQLContext = info.context
        try:
            payload = _input_to_dict(preferences)
            if ctx.user is not None:
                require_authenticated(ctx)
                merged = await update_notification_preferences(
                    ctx.db,
                    user=ctx.user,
                    preferences=payload,
                )
                return _preferences_to_graphql(merged)

            if ctx.contact is not None:
                require_portal(ctx)
                merged = await update_notification_preferences(
                    ctx.db,
                    contact=ctx.contact,
                    preferences=payload,
                )
                return _preferences_to_graphql(merged)

            raise GraphQLError("Authentication required", extensions={"code": "authentication_error"})
        except Exception as exc:
            _gql_error(exc)
            raise
