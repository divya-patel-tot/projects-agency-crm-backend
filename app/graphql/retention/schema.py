from datetime import datetime
from uuid import UUID

import strawberry
from graphql import GraphQLError
from strawberry.types import Info

from app.core.deps import require_authenticated, require_role
from app.core.exceptions import DomainError, NotFoundError
from app.graphql.retention.service import (
    add_sequence_step as add_sequence_step_service,
    cancel_enrollment,
    complete_touchpoint,
    create_sequence_record,
    duplicate_sequence_record,
    enroll_in_sequence,
    get_retention_sequence,
    get_upcoming_touchpoints,
    list_retention_sequences,
    reorder_sequence_steps,
    skip_touchpoint,
    update_sequence_record,
)


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

    @classmethod
    def from_model(cls, row) -> "SequenceStepType":
        return cls(
            id=strawberry.ID(str(row.id)),
            step_order=row.step_order,
            channel=row.channel,
            offset_days=row.offset_days,
            template_id=strawberry.ID(str(row.template_id)) if row.template_id else None,
            assignee_role=row.assignee_role,
        )


@strawberry.type
class RetentionSequenceType:
    id: strawberry.ID
    name: str
    trigger_type: str
    is_active: bool
    is_template: bool

    @classmethod
    def from_model(cls, row) -> "RetentionSequenceType":
        return cls(
            id=strawberry.ID(str(row.id)),
            name=row.name,
            trigger_type=row.trigger_type,
            is_active=row.is_active,
            is_template=row.is_template,
        )

    @strawberry.field
    async def steps(self, info: Info) -> list[SequenceStepType]:
        from app.graphql.retention.repository import list_steps_for_sequence

        ctx = require_authenticated(info.context)
        rows = await list_steps_for_sequence(ctx.db, UUID(str(self.id)))
        return [SequenceStepType.from_model(r) for r in rows]


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


@strawberry.type
class RetentionQuery:
    @strawberry.field
    async def retention_sequences(self, info: Info, active_only: bool = False) -> list[RetentionSequenceType]:
        ctx = require_authenticated(info.context)
        rows = await list_retention_sequences(ctx.db, active_only=active_only)
        return [RetentionSequenceType.from_model(r) for r in rows]

    @strawberry.field
    async def retention_sequence(self, info: Info, id: strawberry.ID) -> RetentionSequenceType | None:
        ctx = require_authenticated(info.context)
        try:
            row = await get_retention_sequence(ctx.db, UUID(str(id)))
            return RetentionSequenceType.from_model(row)
        except NotFoundError:
            return None

    @strawberry.field
    async def upcoming_touchpoints(self, info: Info) -> list[TouchpointType]:
        ctx = require_authenticated(info.context)
        rows = await get_upcoming_touchpoints(ctx.db)
        return [TouchpointType.from_model(r) for r in rows]


@strawberry.type
class RetentionMutation:
    @strawberry.mutation
    async def create_retention_sequence(
        self,
        info: Info,
        name: str,
        trigger_type: str = "manual",
        is_template: bool = False,
    ) -> RetentionSequenceType:
        ctx = require_role(info.context, "admin", "account_manager", "project_manager")
        try:
            row = await create_sequence_record(
                ctx.db,
                actor=ctx.user,
                name=name,
                trigger_type=trigger_type,
                is_template=is_template,
            )
            return RetentionSequenceType.from_model(row)
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def duplicate_retention_sequence(self, info: Info, sequence_id: strawberry.ID) -> RetentionSequenceType:
        ctx = require_role(info.context, "admin", "account_manager")
        try:
            row = await duplicate_sequence_record(ctx.db, actor=ctx.user, sequence_id=UUID(str(sequence_id)))
            return RetentionSequenceType.from_model(row)
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
    ) -> SequenceStepType:
        ctx = require_role(info.context, "admin", "account_manager", "project_manager")
        try:
            row = await add_sequence_step_service(
                ctx.db,
                actor=ctx.user,
                sequence_id=UUID(str(sequence_id)),
                channel=channel,
                offset_days=offset_days,
                template_id=UUID(str(template_id)) if template_id else None,
                assignee_role=assignee_role,
            )
            return SequenceStepType.from_model(row)
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
        ctx = require_role(info.context, "admin", "account_manager", "project_manager")
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
        ctx = require_role(info.context, "admin", "account_manager", "project_manager")
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
        ctx = require_role(info.context, "admin", "account_manager", "project_manager")
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
        ctx = require_role(info.context, "admin", "account_manager", "project_manager")
        try:
            row = await skip_touchpoint(ctx.db, actor=ctx.user, touchpoint_id=UUID(str(id)), notes=notes)
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
    #     ctx = require_role(info.context, "admin", "account_manager")
    #     try:
    #         row = await create_email_template_record(ctx.db, actor=ctx.user, name=name, subject=subject, body=body)
    #         return EmailTemplateType.from_model(row)
    #     except Exception as exc:
    #         _gql_error(exc)
