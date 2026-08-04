from datetime import date, datetime
from uuid import UUID

import strawberry
from graphql import GraphQLError
from strawberry.types import Info

from app.core.deps import require_authenticated, require_portal, require_role
from app.core.exceptions import DomainError, NotFoundError
from app.core.security import ActorType
from app.graphql.change_requests.service import (
    create_change_request,
    decide_change_request,
    get_change_request,
    get_change_request_dashboard,
    get_change_requests,
    get_response_due_at,
    list_portal_cr_approvals,
    portal_resubmit_change_request,
    submit_impact_assessment,
    transition_change_request,
)
from app.graphql.change_requests.ai_assist import draft_impact_assessment as draft_impact_assessment_ai
from app.graphql.change_requests.repository import list_approvals_for_cr
from app.graphql.portal.repository import get_project_for_company


def _gql_error(exc: Exception) -> None:
    if isinstance(exc, (DomainError, NotFoundError)):
        raise GraphQLError(exc.message, extensions={"code": exc.code}) from exc
    raise exc


@strawberry.type
class ChangeRequestApprovalType:
    id: strawberry.ID
    approver_type: str
    status: str
    comment: str | None
    decided_at: datetime | None
    approver_name: str | None

    @classmethod
    def from_model(cls, approval) -> "ChangeRequestApprovalType":
        return cls(
            id=strawberry.ID(str(approval.id)),
            approver_type=approval.approver_type.upper(),
            status=approval.status.upper(),
            comment=approval.comment,
            decided_at=approval.decided_at,
            approver_name=None,
        )


@strawberry.type
class ChangeRequestType:
    id: strawberry.ID
    project_id: strawberry.ID
    company_id: strawberry.ID
    requested_by_contact_id: strawberry.ID | None
    type: str
    title: str
    description: str | None
    priority: str
    status: str
    impact_hours: float | None
    impact_cost: float | None
    impact_timeline_days: int | None
    assessment_notes: str | None
    assigned_pm_id: strawberry.ID | None
    requires_client_approval: bool
    requires_internal_approval: bool
    revision_count: int
    manager_escalation_flagged: bool
    decided_at: datetime | None
    desired_due_date: date | None
    submitted_at: datetime | None
    created_at: datetime
    updated_at: datetime
    _org_id: strawberry.Private[UUID]

    @classmethod
    def from_model(cls, cr) -> "ChangeRequestType":
        return cls(
            id=strawberry.ID(str(cr.id)),
            project_id=strawberry.ID(str(cr.project_id)),
            company_id=strawberry.ID(str(cr.company_id)),
            requested_by_contact_id=strawberry.ID(str(cr.requested_by_contact_id))
            if cr.requested_by_contact_id
            else None,
            type=cr.type,
            title=cr.title,
            description=cr.description,
            priority=cr.priority,
            status=cr.status,
            impact_hours=float(cr.impact_hours) if cr.impact_hours is not None else None,
            impact_cost=float(cr.impact_cost) if cr.impact_cost is not None else None,
            impact_timeline_days=cr.impact_timeline_days,
            assessment_notes=cr.assessment_notes,
            assigned_pm_id=strawberry.ID(str(cr.assigned_pm_id)) if cr.assigned_pm_id else None,
            requires_client_approval=cr.requires_client_approval,
            requires_internal_approval=cr.requires_internal_approval,
            revision_count=cr.revision_count,
            manager_escalation_flagged=cr.manager_escalation_flagged,
            decided_at=cr.decided_at,
            desired_due_date=cr.desired_due_date,
            submitted_at=cr.submitted_at,
            created_at=cr.created_at,
            updated_at=cr.updated_at,
            _org_id=cr.org_id,
        )

    @strawberry.field
    async def approvals(self, info: Info) -> list[ChangeRequestApprovalType]:
        rows = await list_approvals_for_cr(info.context.db, UUID(str(self.id)))
        return [ChangeRequestApprovalType.from_model(row) for row in rows]

    @strawberry.field
    async def response_due_at(self, info: Info) -> datetime | None:
        due_at, _ = await get_response_due_at(
            info.context.db, org_id=self._org_id, status=self.status, submitted_at=self.submitted_at
        )
        return due_at

    @strawberry.field
    async def is_overdue(self, info: Info) -> bool:
        _, overdue = await get_response_due_at(
            info.context.db, org_id=self._org_id, status=self.status, submitted_at=self.submitted_at
        )
        return overdue


@strawberry.type
class ImpactAssessmentDraftType:
    impact_hours: float | None
    impact_cost: float | None
    impact_timeline_days: int | None
    assessment_notes: str | None
    advisory: bool = True


@strawberry.type
class ChangeRequestDashboardType:
    open_count: int
    pending_approval_count: int
    overdue_count: int
    sla_days: int
    aging_by_status: strawberry.scalars.JSON


@strawberry.type
class ChangeRequestQuery:
    @strawberry.field
    async def change_requests(
        self,
        info: Info,
        project_id: strawberry.ID,
        status: str | None = None,
    ) -> list[ChangeRequestType]:
        ctx = require_authenticated(info.context)
        try:
            rows = await get_change_requests(
                ctx.db,
                project_id=UUID(str(project_id)),
                status=status,
            )
            return [ChangeRequestType.from_model(row) for row in rows]
        except Exception as exc:
            _gql_error(exc)

    @strawberry.field
    async def change_request(self, info: Info, id: strawberry.ID) -> ChangeRequestType | None:
        ctx = require_authenticated(info.context)
        row = await get_change_request(ctx.db, UUID(str(id)))
        return ChangeRequestType.from_model(row) if row else None

    @strawberry.field
    async def change_request_dashboard(self, info: Info) -> ChangeRequestDashboardType:
        ctx = require_authenticated(info.context)
        data = await get_change_request_dashboard(ctx.db, org_id=ctx.org.id)
        return ChangeRequestDashboardType(
            open_count=data["open_count"],
            pending_approval_count=data["pending_approval_count"],
            overdue_count=data["overdue_count"],
            sla_days=data["sla_days"],
            aging_by_status=data["aging_by_status"],
        )


@strawberry.type
class ChangeRequestMutation:
    @strawberry.mutation
    async def transition_change_request(
        self,
        info: Info,
        id: strawberry.ID,
        to_status: str,
        reason: str | None = None,
    ) -> ChangeRequestType:
        ctx = require_role(info.context, "project_manager", "admin")
        try:
            row = await transition_change_request(
                ctx.db,
                actor=ctx.user,
                cr_id=UUID(str(id)),
                to_status=to_status,
                reason=reason,
            )
            return ChangeRequestType.from_model(row)
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def submit_impact_assessment(
        self,
        info: Info,
        id: strawberry.ID,
        impact_hours: float | None = None,
        impact_cost: float | None = None,
        impact_timeline_days: int | None = None,
        assessment_notes: str | None = None,
    ) -> ChangeRequestType:
        ctx = require_role(info.context, "project_manager", "admin")
        try:
            row = await submit_impact_assessment(
                ctx.db,
                actor=ctx.user,
                cr_id=UUID(str(id)),
                impact_hours=impact_hours,
                impact_cost=impact_cost,
                impact_timeline_days=impact_timeline_days,
                assessment_notes=assessment_notes,
            )
            return ChangeRequestType.from_model(row)
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def decide_change_request(
        self,
        info: Info,
        id: strawberry.ID,
        approval_id: strawberry.ID,
        decision: str,
        comment: str | None = None,
        apply_financial_impact: bool = False,
    ) -> ChangeRequestType:
        if info.context.actor_type == ActorType.PORTAL:
            ctx = require_portal(info.context)
            try:
                row = await decide_change_request(
                    ctx.db,
                    cr_id=UUID(str(id)),
                    approval_id=UUID(str(approval_id)),
                    decision=decision,
                    comment=comment,
                    apply_financial_impact=False,
                    portal_contact=ctx.contact,
                )
                return ChangeRequestType.from_model(row)
            except Exception as exc:
                _gql_error(exc)

        ctx = require_role(info.context, "project_manager", "admin")
        try:
            row = await decide_change_request(
                ctx.db,
                cr_id=UUID(str(id)),
                approval_id=UUID(str(approval_id)),
                decision=decision,
                comment=comment,
                apply_financial_impact=apply_financial_impact,
                internal_actor=ctx.user,
            )
            return ChangeRequestType.from_model(row)
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def create_change_request(
        self,
        info: Info,
        project_id: strawberry.ID,
        title: str,
        type: str,
        description: str | None = None,
        priority: str = "medium",
        desired_due_date: date | None = None,
    ) -> ChangeRequestType:
        if info.context.actor_type == ActorType.PORTAL:
            ctx = require_portal(info.context)
            project = await get_project_for_company(
                ctx.db,
                project_id=UUID(str(project_id)),
                company_id=ctx.company_id,
            )
            if project is None:
                raise GraphQLError("Project not found", extensions={"code": "not_found"})
            try:
                row = await create_change_request(
                    ctx.db,
                    org_id=ctx.org.id,
                    project_id=project.id,
                    company_id=ctx.company_id,
                    title=title,
                    description=description,
                    cr_type=type,
                    priority=priority,
                    requested_by_contact_id=ctx.contact.id,
                    desired_due_date=desired_due_date,
                    actor_id=ctx.contact.id,
                )
                return ChangeRequestType.from_model(row)
            except Exception as exc:
                _gql_error(exc)

        ctx = require_authenticated(info.context)
        from app.graphql.change_requests.repository import get_project_for_cr

        project = await get_project_for_cr(ctx.db, UUID(str(project_id)))
        if project is None:
            raise GraphQLError("Project not found", extensions={"code": "not_found"})
        try:
            row = await create_change_request(
                ctx.db,
                org_id=ctx.org.id,
                project_id=project.id,
                company_id=project.company_id,
                title=title,
                description=description,
                cr_type=type,
                priority=priority,
                desired_due_date=desired_due_date,
                actor_id=ctx.user.id,
            )
            return ChangeRequestType.from_model(row)
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def draft_impact_assessment(self, info: Info, id: strawberry.ID) -> ImpactAssessmentDraftType | None:
        ctx = require_role(info.context, "project_manager", "admin")
        try:
            draft = await draft_impact_assessment_ai(
                ctx.db,
                actor=ctx.user,
                cr_id=UUID(str(id)),
            )
            if draft is None:
                return None
            return ImpactAssessmentDraftType(
                impact_hours=draft.impact_hours,
                impact_cost=draft.impact_cost,
                impact_timeline_days=draft.impact_timeline_days,
                assessment_notes=draft.assessment_notes,
                advisory=True,
            )
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def resubmit_change_request(self, info: Info, id: strawberry.ID) -> ChangeRequestType:
        ctx = require_portal(info.context)
        try:
            row = await portal_resubmit_change_request(ctx.db, contact=ctx.contact, cr_id=UUID(str(id)))
            return ChangeRequestType.from_model(row)
        except Exception as exc:
            _gql_error(exc)
