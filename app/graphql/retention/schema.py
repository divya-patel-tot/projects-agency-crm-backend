from __future__ import annotations

from datetime import datetime
from uuid import UUID

import strawberry
from graphql import GraphQLError
from sqlalchemy import func, select
from strawberry.types import Info

from app.core.deps import require_authenticated, require_role
from app.core.exceptions import DomainError, NotFoundError
from app.db.enums import EnrollmentStatus
from app.db.models.retention import RetentionEnrollment
from app.graphql.companies.schema import CompanyType, company_from_model
from app.graphql.companies.service import get_companies, get_company_by_id
from app.graphql.contacts.schema import ContactType
from app.graphql.retention.eligibility import get_company_retention_eligibility
from app.graphql.retention.service import (
    add_sequence_step as add_sequence_step_service,
    approve_retention_sequence,
    cancel_enrollment,
    complete_touchpoint,
    create_sequence_record,
    duplicate_sequence_record,
    enroll_in_sequence,
    generate_ai_retention_sequence,
    get_retention_sequence,
    get_touchpoints_for_company,
    get_upcoming_touchpoints,
    list_retention_sequences,
    log_touchpoint as log_touchpoint_service,
    reject_retention_sequence,
    remove_sequence_step as remove_sequence_step_service,
    reorder_sequence_steps as reorder_sequence_steps_service,
    skip_touchpoint,
    submit_sequence_for_approval,
    update_sequence_record,
    update_sequence_step as update_sequence_step_service,
)
from app.graphql.users.schema import UserSummaryType


def _gql_error(exc: Exception) -> None:
    if isinstance(exc, (DomainError, NotFoundError)):
        raise GraphQLError(exc.message, extensions={"code": exc.code}) from exc
    raise exc


@strawberry.type
class EmailTemplateType:
    id: strawberry.ID
    name: str
    subject: str
    body: str

    @classmethod
    def from_model(cls, row) -> "EmailTemplateType":
        return cls(
            id=strawberry.ID(str(row.id)),
            name=row.name,
            subject=row.subject,
            body=row.body,
        )


@strawberry.type
class SequenceStepType:
    id: strawberry.ID
    step_order: int
    channel: str
    offset_days: int
    template_id: strawberry.ID | None
    assignee_role: str | None
    name: str | None
    action_message: str | None

    @classmethod
    def from_model(cls, row) -> "SequenceStepType":
        return cls(
            id=strawberry.ID(str(row.id)),
            step_order=row.step_order,
            channel=row.channel,
            offset_days=row.offset_days,
            template_id=strawberry.ID(str(row.template_id)) if row.template_id else None,
            assignee_role=row.assignee_role,
            name=row.name,
            action_message=row.action_message,
        )


@strawberry.type
class RetentionSequenceType:
    id: strawberry.ID
    name: str
    trigger_type: str
    is_active: bool
    is_template: bool
    description: str | None
    status: str
    source: str
    company_id: strawberry.ID | None
    created_at: datetime
    approved_at: datetime | None
    rejection_reason: str | None
    ai_rationale: str | None

    @classmethod
    def from_model(cls, row) -> "RetentionSequenceType":
        return cls(
            id=strawberry.ID(str(row.id)),
            name=row.name,
            trigger_type=row.trigger_type,
            is_active=row.is_active,
            is_template=row.is_template,
            description=row.description,
            status=row.status,
            source=row.source,
            company_id=strawberry.ID(str(row.company_id)) if row.company_id else None,
            created_at=row.created_at,
            approved_at=row.approved_at,
            rejection_reason=row.rejection_reason,
            ai_rationale=row.ai_rationale,
        )

    @strawberry.field
    async def company(self, info: Info) -> CompanyType | None:
        if not self.company_id:
            return None
        from app.graphql.companies.service import get_company_by_id

        ctx = require_authenticated(info.context)
        try:
            company = await get_company_by_id(ctx.db, UUID(str(self.company_id)), actor=ctx.user)
            return company_from_model(company)
        except Exception:
            return None

    @strawberry.field
    async def created_by(self, info: Info) -> UserSummaryType | None:
        from app.db.models.user import User

        ctx = require_authenticated(info.context)
        seq = await get_retention_sequence(ctx.db, UUID(str(self.id)), actor=ctx.user)
        if not seq.created_by_id:
            return None
        user = await ctx.db.get(User, seq.created_by_id)
        return UserSummaryType.from_model(user) if user else None

    @strawberry.field
    async def approved_by(self, info: Info) -> UserSummaryType | None:
        from app.db.models.user import User

        ctx = require_authenticated(info.context)
        seq = await get_retention_sequence(ctx.db, UUID(str(self.id)), actor=ctx.user)
        if not seq.approved_by_id:
            return None
        user = await ctx.db.get(User, seq.approved_by_id)
        return UserSummaryType.from_model(user) if user else None

    @strawberry.field
    async def steps(self, info: Info) -> list[SequenceStepType]:
        from app.graphql.retention.repository import list_steps_for_sequence

        ctx = require_authenticated(info.context)
        rows = await list_steps_for_sequence(ctx.db, UUID(str(self.id)))
        return [SequenceStepType.from_model(r) for r in rows]

    @strawberry.field
    async def enrollments(self, info: Info) -> list[RetentionEnrollmentType]:
        from app.graphql.retention.repository import list_enrollments_for_sequence

        ctx = require_authenticated(info.context)
        rows = await list_enrollments_for_sequence(ctx.db, UUID(str(self.id)))
        return [RetentionEnrollmentType.from_model(r) for r in rows]

    @strawberry.field
    async def active_enrollment_count(self, info: Info) -> int:
        ctx = require_authenticated(info.context)
        result = await ctx.db.execute(
            select(func.count())
            .select_from(RetentionEnrollment)
            .where(
                RetentionEnrollment.sequence_id == UUID(str(self.id)),
                RetentionEnrollment.status == EnrollmentStatus.ACTIVE.value,
            )
        )
        return int(result.scalar_one())


@strawberry.type
class RetentionEnrollmentType:
    id: strawberry.ID
    sequence_id: strawberry.ID
    company_id: strawberry.ID
    contact_id: strawberry.ID
    project_id: strawberry.ID | None
    status: str
    current_step: int
    enrolled_at: datetime

    @classmethod
    def from_model(cls, row) -> "RetentionEnrollmentType":
        return cls(
            id=strawberry.ID(str(row.id)),
            sequence_id=strawberry.ID(str(row.sequence_id)),
            company_id=strawberry.ID(str(row.company_id)),
            contact_id=strawberry.ID(str(row.contact_id)),
            project_id=strawberry.ID(str(row.project_id)) if row.project_id else None,
            status=row.status,
            current_step=row.current_step,
            enrolled_at=row.enrolled_at,
        )

    @strawberry.field
    async def sequence(self, info: Info) -> RetentionSequenceType | None:
        from app.graphql.retention.repository import get_sequence

        ctx = require_authenticated(info.context)
        row = await get_sequence(ctx.db, UUID(str(self.sequence_id)))
        return RetentionSequenceType.from_model(row) if row else None

    @strawberry.field
    async def company(self, info: Info) -> CompanyType | None:
        from app.db.models.company import Company

        ctx = require_authenticated(info.context)
        company = await ctx.db.get(Company, UUID(str(self.company_id)))
        if company is None or company.deleted_at is not None:
            return None
        return company_from_model(company)

    @strawberry.field
    async def contact(self, info: Info) -> ContactType | None:
        from app.db.models.contact import Contact

        ctx = require_authenticated(info.context)
        contact = await ctx.db.get(Contact, UUID(str(self.contact_id)))
        if contact is None or contact.deleted_at is not None:
            return None
        return ContactType.from_model(contact)


@strawberry.type
class TouchpointType:
    id: strawberry.ID
    enrollment_id: strawberry.ID | None
    company_id: strawberry.ID
    contact_id: strawberry.ID
    type: str
    scheduled_at: datetime
    completed_at: datetime | None
    status: str
    outcome: str | None
    notes: str | None

    @classmethod
    def from_model(cls, row) -> "TouchpointType":
        return cls(
            id=strawberry.ID(str(row.id)),
            enrollment_id=strawberry.ID(str(row.enrollment_id)) if row.enrollment_id else None,
            company_id=strawberry.ID(str(row.company_id)),
            contact_id=strawberry.ID(str(row.contact_id)),
            type=row.type,
            scheduled_at=row.scheduled_at,
            completed_at=row.completed_at,
            status=row.status,
            outcome=row.outcome,
            notes=row.notes,
        )

    @strawberry.field
    async def contact(self, info: Info) -> ContactType | None:
        from app.db.models.contact import Contact

        ctx = require_authenticated(info.context)
        contact = await ctx.db.get(Contact, UUID(str(self.contact_id)))
        if contact is None or contact.deleted_at is not None:
            return None
        return ContactType.from_model(contact)


@strawberry.type
class RetentionBlockingProjectType:
    id: strawberry.ID
    name: str
    status: str


@strawberry.type
class CompanyRetentionEligibilityType:
    eligible: bool
    reason: str | None
    completed_project_count: int
    incomplete_project_count: int
    blocking_projects: list[RetentionBlockingProjectType]

    @classmethod
    def from_result(cls, result) -> "CompanyRetentionEligibilityType":
        return cls(
            eligible=result.eligible,
            reason=result.reason,
            completed_project_count=result.completed_project_count,
            incomplete_project_count=result.incomplete_project_count,
            blocking_projects=[
                RetentionBlockingProjectType(
                    id=strawberry.ID(str(project_id)),
                    name=name,
                    status=status,
                )
                for project_id, name, status in result.blocking_projects
            ],
        )


@strawberry.type
class RetentionQuery:
    @strawberry.field
    async def retention_sequences(
        self,
        info: Info,
        active_only: bool = False,
        company_id: strawberry.ID | None = None,
        status: str | None = None,
        source: str | None = None,
        created_by_id: strawberry.ID | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        search: str | None = None,
    ) -> list[RetentionSequenceType]:
        ctx = require_role(info.context, "admin", "project_manager")
        rows = await list_retention_sequences(
            ctx.db,
            actor=ctx.user,
            active_only=active_only,
            company_id=UUID(str(company_id)) if company_id else None,
            status=status,
            source=source,
            created_by_id=UUID(str(created_by_id)) if created_by_id else None,
            created_after=created_after,
            created_before=created_before,
            search=search,
        )
        return [RetentionSequenceType.from_model(r) for r in rows]

    @strawberry.field
    async def retention_sequence(self, info: Info, id: strawberry.ID) -> RetentionSequenceType | None:
        ctx = require_role(info.context, "admin", "project_manager")
        try:
            row = await get_retention_sequence(ctx.db, UUID(str(id)), actor=ctx.user)
            return RetentionSequenceType.from_model(row)
        except NotFoundError:
            return None

    @strawberry.field
    async def upcoming_touchpoints(self, info: Info) -> list[TouchpointType]:
        ctx = require_role(info.context, "admin", "project_manager")
        rows = await get_upcoming_touchpoints(ctx.db)
        return [TouchpointType.from_model(r) for r in rows]

    @strawberry.field(description="Full touchpoint history for a company — scheduled, completed and skipped.")
    async def company_touchpoints(self, info: Info, company_id: strawberry.ID) -> list[TouchpointType]:
        ctx = require_authenticated(info.context)
        try:
            await get_company_by_id(ctx.db, UUID(str(company_id)), actor=ctx.user)
        except NotFoundError:
            return []
        rows = await get_touchpoints_for_company(ctx.db, UUID(str(company_id)))
        return [TouchpointType.from_model(r) for r in rows]

    @strawberry.field
    async def company_retention_eligibility(
        self,
        info: Info,
        company_id: strawberry.ID,
    ) -> CompanyRetentionEligibilityType:
        ctx = require_role(info.context, "admin", "project_manager")
        await get_company_by_id(ctx.db, UUID(str(company_id)), actor=ctx.user)
        result = await get_company_retention_eligibility(ctx.db, UUID(str(company_id)))
        return CompanyRetentionEligibilityType.from_result(result)

    @strawberry.field
    async def retention_eligible_companies(self, info: Info) -> list[CompanyType]:
        ctx = require_role(info.context, "admin", "project_manager")
        companies = await get_companies(ctx.db, actor=ctx.user)
        eligible: list[CompanyType] = []
        for company in companies:
            result = await get_company_retention_eligibility(ctx.db, company.id)
            if result.eligible:
                eligible.append(company_from_model(company))
        return eligible


@strawberry.type
class RetentionMutation:
    @strawberry.mutation
    async def create_retention_sequence(
        self,
        info: Info,
        name: str,
        company_id: strawberry.ID,
        trigger_type: str = "manual",
        description: str | None = None,
        is_template: bool = False,
        submit_for_approval: bool = False,
    ) -> RetentionSequenceType:
        ctx = require_role(info.context, "admin", "project_manager")
        try:
            status = "pending" if submit_for_approval else "draft"
            row = await create_sequence_record(
                ctx.db,
                actor=ctx.user,
                name=name,
                company_id=UUID(str(company_id)),
                trigger_type=trigger_type,
                description=description,
                is_active=False,
                is_template=is_template,
                status=status,
            )
            return RetentionSequenceType.from_model(row)
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def generate_retention_sequence(self, info: Info, company_id: strawberry.ID) -> RetentionSequenceType:
        ctx = require_role(info.context, "admin", "project_manager")
        try:
            row = await generate_ai_retention_sequence(
                ctx.db,
                actor=ctx.user,
                company_id=UUID(str(company_id)),
            )
            return RetentionSequenceType.from_model(row)
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def submit_retention_sequence(self, info: Info, id: strawberry.ID) -> RetentionSequenceType:
        ctx = require_role(info.context, "admin", "project_manager")
        try:
            row = await submit_sequence_for_approval(ctx.db, actor=ctx.user, sequence_id=UUID(str(id)))
            return RetentionSequenceType.from_model(row)
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def approve_retention_sequence(self, info: Info, id: strawberry.ID) -> RetentionSequenceType:
        ctx = require_role(info.context, "admin", "project_manager")
        try:
            row = await approve_retention_sequence(ctx.db, actor=ctx.user, sequence_id=UUID(str(id)))
            return RetentionSequenceType.from_model(row)
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def reject_retention_sequence(
        self,
        info: Info,
        id: strawberry.ID,
        reason: str | None = None,
    ) -> RetentionSequenceType:
        ctx = require_role(info.context, "admin", "project_manager")
        try:
            row = await reject_retention_sequence(
                ctx.db,
                actor=ctx.user,
                sequence_id=UUID(str(id)),
                reason=reason,
            )
            return RetentionSequenceType.from_model(row)
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def duplicate_retention_sequence(self, info: Info, sequence_id: strawberry.ID) -> RetentionSequenceType:
        ctx = require_role(info.context, "admin", "project_manager")
        try:
            row = await duplicate_sequence_record(ctx.db, actor=ctx.user, sequence_id=UUID(str(sequence_id)))
            return RetentionSequenceType.from_model(row)
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def update_retention_sequence(
        self,
        info: Info,
        id: strawberry.ID,
        name: str | None = None,
        trigger_type: str | None = None,
        description: str | None = None,
        company_id: strawberry.ID | None = None,
        is_active: bool | None = None,
    ) -> RetentionSequenceType:
        ctx = require_role(info.context, "admin", "project_manager")
        try:
            row = await update_sequence_record(
                ctx.db,
                actor=ctx.user,
                sequence_id=UUID(str(id)),
                updates={
                    "name": name,
                    "trigger_type": trigger_type,
                    "description": description,
                    "company_id": UUID(str(company_id)) if company_id else None,
                    "is_active": is_active,
                },
            )
            return RetentionSequenceType.from_model(row)
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def remove_sequence_step(self, info: Info, step_id: strawberry.ID) -> bool:
        ctx = require_role(info.context, "admin", "project_manager")
        try:
            await remove_sequence_step_service(ctx.db, actor=ctx.user, step_id=UUID(str(step_id)))
            return True
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def add_sequence_step(
        self,
        info: Info,
        sequence_id: strawberry.ID,
        channel: str,
        offset_days: int,
        template_id: strawberry.ID | None = None,
        assignee_role: str | None = None,
        name: str | None = None,
        action_message: str | None = None,
    ) -> SequenceStepType:
        ctx = require_role(info.context, "admin", "project_manager")
        try:
            row = await add_sequence_step_service(
                ctx.db,
                actor=ctx.user,
                sequence_id=UUID(str(sequence_id)),
                channel=channel,
                offset_days=offset_days,
                template_id=UUID(str(template_id)) if template_id else None,
                assignee_role=assignee_role,
                name=name,
                action_message=action_message,
            )
            return SequenceStepType.from_model(row)
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def update_sequence_step(
        self,
        info: Info,
        step_id: strawberry.ID,
        channel: str | None = None,
        offset_days: int | None = None,
        assignee_role: str | None = None,
        name: str | None = None,
        action_message: str | None = None,
    ) -> SequenceStepType:
        ctx = require_role(info.context, "admin", "project_manager")
        try:
            row = await update_sequence_step_service(
                ctx.db,
                actor=ctx.user,
                step_id=UUID(str(step_id)),
                channel=channel,
                offset_days=offset_days,
                assignee_role=assignee_role,
                name=name,
                action_message=action_message,
            )
            return SequenceStepType.from_model(row)
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def reorder_sequence_steps(
        self,
        info: Info,
        sequence_id: strawberry.ID,
        ordered_step_ids: list[strawberry.ID],
    ) -> list[SequenceStepType]:
        ctx = require_role(info.context, "admin", "project_manager")
        try:
            rows = await reorder_sequence_steps_service(
                ctx.db,
                actor=ctx.user,
                sequence_id=UUID(str(sequence_id)),
                ordered_step_ids=[UUID(str(step_id)) for step_id in ordered_step_ids],
            )
            return [SequenceStepType.from_model(r) for r in rows]
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def enroll_in_sequence(
        self,
        info: Info,
        sequence_id: strawberry.ID,
        company_id: strawberry.ID,
        contact_id: strawberry.ID,
        project_id: strawberry.ID | None = None,
    ) -> RetentionEnrollmentType:
        ctx = require_role(info.context, "admin", "project_manager")
        try:
            row = await enroll_in_sequence(
                ctx.db,
                actor=ctx.user,
                sequence_id=UUID(str(sequence_id)),
                company_id=UUID(str(company_id)),
                contact_id=UUID(str(contact_id)),
                project_id=UUID(str(project_id)) if project_id else None,
            )
            return RetentionEnrollmentType.from_model(row)
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def cancel_enrollment(self, info: Info, enrollment_id: strawberry.ID) -> RetentionEnrollmentType:
        ctx = require_role(info.context, "admin", "project_manager")
        try:
            row = await cancel_enrollment(ctx.db, actor=ctx.user, enrollment_id=UUID(str(enrollment_id)))
            return RetentionEnrollmentType.from_model(row)
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def complete_touchpoint(
        self,
        info: Info,
        id: strawberry.ID,
        outcome: str | None = None,
        notes: str | None = None,
    ) -> TouchpointType:
        ctx = require_role(info.context, "admin", "project_manager")
        try:
            row = await complete_touchpoint(
                ctx.db,
                actor=ctx.user,
                touchpoint_id=UUID(str(id)),
                outcome=outcome,
                notes=notes,
            )
            return TouchpointType.from_model(row)
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def skip_touchpoint(self, info: Info, id: strawberry.ID, notes: str | None = None) -> TouchpointType:
        ctx = require_role(info.context, "admin", "project_manager")
        try:
            row = await skip_touchpoint(ctx.db, actor=ctx.user, touchpoint_id=UUID(str(id)), notes=notes)
            return TouchpointType.from_model(row)
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation(description="Record a touchpoint that already happened — a call made, a meeting held.")
    async def log_touchpoint(
        self,
        info: Info,
        company_id: strawberry.ID,
        contact_id: strawberry.ID,
        type: str,
        outcome: str | None = None,
        notes: str | None = None,
        project_id: strawberry.ID | None = None,
        occurred_at: datetime | None = None,
    ) -> TouchpointType:
        ctx = require_role(info.context, "admin", "project_manager")
        try:
            row = await log_touchpoint_service(
                ctx.db,
                actor=ctx.user,
                company_id=UUID(str(company_id)),
                contact_id=UUID(str(contact_id)),
                type=type,
                outcome=outcome,
                notes=notes,
                project_id=UUID(str(project_id)) if project_id else None,
                occurred_at=occurred_at,
            )
            return TouchpointType.from_model(row)
        except Exception as exc:
            _gql_error(exc)

    # Mail disabled — email templates are not exposed via GraphQL while EMAIL_FEATURES_ENABLED=false.
    # @strawberry.mutation
    # async def create_email_template(
    #     self,
    #     info: Info,
    #     name: str,
    #     subject: str,
    #     body: str,
    # ) -> EmailTemplateType:
    #     ctx = require_role(info.context, "admin")
    #     try:
    #         row = await create_email_template_record(ctx.db, actor=ctx.user, name=name, subject=subject, body=body)
    #         return EmailTemplateType.from_model(row)
    #     except Exception as exc:
    #         _gql_error(exc)
