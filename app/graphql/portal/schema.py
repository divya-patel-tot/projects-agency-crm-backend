from datetime import datetime
from uuid import UUID

import strawberry
from graphql import GraphQLError
from strawberry.types import Info

from app.core.deps import enforce_portal_company_id, require_authenticated, require_portal, require_role
from app.core.exceptions import DomainError, NotFoundError
from app.core.security import ActorType
from app.graphql.approvals.service import (
    approve_milestone,
    list_pending_portal_approvals,
    mark_milestone_ready_for_review,
    request_milestone_changes,
)
from app.graphql.documents.service import confirm_upload, get_entity_documents, get_portal_documents, request_upload_url
from app.graphql.loaders import get_phases_by_project_loader, get_tasks_by_project_loader
from app.graphql.planning.schema import PhaseType, TaskType
from app.graphql.portal.repository import get_company_by_id, get_project_for_company, get_projects_for_company


def _gql_error(exc: Exception) -> None:
    if isinstance(exc, (DomainError, NotFoundError)):
        raise GraphQLError(exc.message, extensions={"code": exc.code}) from exc
    raise exc


@strawberry.type
class PortalCompanyType:
    id: strawberry.ID
    name: str
    industry: str | None
    website: str | None
    status: str

    @classmethod
    def from_model(cls, company) -> "PortalCompanyType":
        return cls(
            id=strawberry.ID(str(company.id)),
            name=company.name,
            industry=company.industry,
            website=company.website,
            status=company.status,
        )


@strawberry.type
class PortalProjectType:
    """Portal-facing project — financial fields intentionally omitted."""

    id: strawberry.ID
    name: str
    description: str | None
    status: str
    priority: str | None
    health: str | None

    @classmethod
    def from_model(cls, project) -> "PortalProjectType":
        return cls(
            id=strawberry.ID(str(project.id)),
            name=project.name,
            description=project.description,
            status=project.status,
            priority=project.priority,
            health=project.health,
        )

    @strawberry.field
    async def phases(self, info: Info) -> list[PhaseType]:
        loader = get_phases_by_project_loader(info.context)
        rows = await loader.load(UUID(str(self.id)))
        return [PhaseType.from_model(row) for row in rows]

    @strawberry.field
    async def tasks(self, info: Info) -> list[TaskType]:
        loader = get_tasks_by_project_loader(info.context)
        rows = await loader.load(UUID(str(self.id)))
        return [TaskType.from_model(row) for row in rows]


@strawberry.type
class ApprovalType:
    id: strawberry.ID
    entity_type: str
    entity_id: strawberry.ID
    approver_type: str
    status: str
    comment: str | None
    decided_at: datetime | None

    @classmethod
    def from_model(cls, approval) -> "ApprovalType":
        return cls(
            id=strawberry.ID(str(approval.id)),
            entity_type=approval.entity_type,
            entity_id=strawberry.ID(str(approval.entity_id)),
            approver_type=approval.approver_type,
            status=approval.status,
            comment=approval.comment,
            decided_at=approval.decided_at,
        )


@strawberry.type
class DocumentType:
    id: strawberry.ID
    entity_type: str
    entity_id: strawberry.ID
    file_url: str
    version: int
    uploaded_by: strawberry.ID

    @classmethod
    def from_model(cls, document) -> "DocumentType":
        return cls(
            id=strawberry.ID(str(document.id)),
            entity_type=document.entity_type,
            entity_id=strawberry.ID(str(document.entity_id)),
            file_url=document.file_url,
            version=document.version,
            uploaded_by=strawberry.ID(str(document.uploaded_by)),
        )


@strawberry.type
class UploadUrlPayload:
    upload_url: str
    file_url: str
    upload_token: str


@strawberry.type
class PortalQuery:
    @strawberry.field
    async def portal_company(self, info: Info, company_id: strawberry.ID | None = None) -> PortalCompanyType | None:
        ctx = require_portal(info.context)
        cid = enforce_portal_company_id(ctx, UUID(str(company_id)) if company_id else None)
        company = await get_company_by_id(ctx.db, cid)
        return PortalCompanyType.from_model(company) if company else None

    @strawberry.field
    async def portal_projects(
        self,
        info: Info,
        company_id: strawberry.ID | None = None,
    ) -> list[PortalProjectType]:
        ctx = require_portal(info.context)
        cid = enforce_portal_company_id(ctx, UUID(str(company_id)) if company_id else None)
        rows = await get_projects_for_company(ctx.db, company_id=cid)
        return [PortalProjectType.from_model(row) for row in rows]

    @strawberry.field
    async def portal_project(self, info: Info, id: strawberry.ID) -> PortalProjectType | None:
        ctx = require_portal(info.context)
        row = await get_project_for_company(ctx.db, project_id=UUID(str(id)), company_id=ctx.company_id)
        return PortalProjectType.from_model(row) if row else None

    @strawberry.field
    async def portal_pending_approvals(self, info: Info) -> list[ApprovalType]:
        ctx = require_portal(info.context)
        rows = await list_pending_portal_approvals(ctx.db, company_id=ctx.company_id)
        return [ApprovalType.from_model(row) for row in rows]

    @strawberry.field
    async def portal_documents(self, info: Info) -> list[DocumentType]:
        ctx = require_portal(info.context)
        rows = await get_portal_documents(ctx.db, company_id=ctx.company_id)
        return [DocumentType.from_model(row) for row in rows]


@strawberry.type
class ApprovalMutation:
    @strawberry.mutation
    async def mark_milestone_ready_for_review(self, info: Info, milestone_id: strawberry.ID) -> ApprovalType:
        ctx = require_role(info.context, "project_manager", "admin")
        try:
            row = await mark_milestone_ready_for_review(
                ctx.db,
                org_id=ctx.org.id,
                milestone_id=UUID(str(milestone_id)),
            )
            return ApprovalType.from_model(row)
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def approve_milestone(self, info: Info, approval_id: strawberry.ID) -> ApprovalType:
        ctx = require_portal(info.context)
        try:
            row = await approve_milestone(
                ctx.db,
                approval_id=UUID(str(approval_id)),
                company_id=ctx.company_id,
                contact_id=ctx.contact.id,
            )
            return ApprovalType.from_model(row)
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def request_milestone_changes(
        self,
        info: Info,
        approval_id: strawberry.ID,
        comment: str,
    ) -> ApprovalType:
        ctx = require_portal(info.context)
        try:
            row = await request_milestone_changes(
                ctx.db,
                approval_id=UUID(str(approval_id)),
                company_id=ctx.company_id,
                contact_id=ctx.contact.id,
                comment=comment,
            )
            return ApprovalType.from_model(row)
        except Exception as exc:
            _gql_error(exc)


@strawberry.type
class DocumentMutation:
    @strawberry.mutation
    async def request_upload_url(
        self,
        info: Info,
        entity_type: str,
        entity_id: strawberry.ID,
        filename: str,
        content_type: str,
    ) -> UploadUrlPayload:
        if info.context.actor_type == ActorType.PORTAL:
            ctx = require_portal(info.context)
            company_id = ctx.company_id
        else:
            ctx = require_authenticated(info.context)
            company_id = None
        try:
            result = await request_upload_url(
                ctx.db,
                org_id=ctx.org.id,
                company_id=company_id,
                actor_type=ctx.actor_type,
                entity_type=entity_type,
                entity_id=UUID(str(entity_id)),
                filename=filename,
                content_type=content_type,
                upload_base_url=str(ctx.request.base_url).rstrip("/"),
            )
            return UploadUrlPayload(
                upload_url=result.upload_url,
                file_url=result.file_url,
                upload_token=result.upload_token,
            )
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def confirm_upload(
        self,
        info: Info,
        entity_type: str,
        entity_id: strawberry.ID,
        file_url: str,
    ) -> DocumentType:
        if info.context.actor_type == ActorType.PORTAL:
            ctx = require_portal(info.context)
            actor_id = ctx.contact.id
            company_id = ctx.company_id
        else:
            ctx = require_authenticated(info.context)
            actor_id = ctx.user.id
            company_id = None
        try:
            row = await confirm_upload(
                ctx.db,
                org_id=ctx.org.id,
                company_id=company_id,
                actor_type=ctx.actor_type,
                actor_id=actor_id,
                entity_type=entity_type,
                entity_id=UUID(str(entity_id)),
                file_url=file_url,
            )
            return DocumentType.from_model(row)
        except Exception as exc:
            _gql_error(exc)


@strawberry.type
class DocumentQuery:
    @strawberry.field
    async def documents(
        self,
        info: Info,
        entity_type: str,
        entity_id: strawberry.ID,
    ) -> list[DocumentType]:
        if info.context.actor_type == ActorType.PORTAL:
            ctx = require_portal(info.context)
            if entity_type == "project":
                project = await get_project_for_company(
                    ctx.db,
                    project_id=UUID(str(entity_id)),
                    company_id=ctx.company_id,
                )
                if project is None:
                    return []
            rows = await get_entity_documents(
                ctx.db,
                entity_type=entity_type,
                entity_id=UUID(str(entity_id)),
            )
        else:
            ctx = require_authenticated(info.context)
            rows = await get_entity_documents(
                ctx.db,
                entity_type=entity_type,
                entity_id=UUID(str(entity_id)),
            )
        return [DocumentType.from_model(row) for row in rows]
