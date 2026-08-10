from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

import strawberry
from graphql import GraphQLError
from strawberry.types import Info

from app.core.deps import require_authenticated, require_role
from app.core.exceptions import DomainError, NotFoundError
from app.db.enums import Currency
from app.graphql.invoices.service import (
    create_invoice_record,
    delete_invoice_record,
    get_invoice_by_id,
    get_invoices,
    update_invoice_record,
)
from app.graphql.loaders import get_projects_by_company_loader


def _gql_error(exc: Exception) -> None:
    if isinstance(exc, (DomainError, NotFoundError)):
        raise GraphQLError(exc.message, extensions={"code": exc.code}) from exc
    raise exc


@strawberry.type
class InvoiceType:
    id: strawberry.ID
    company_id: strawberry.ID
    project_id: strawberry.ID | None
    invoice_number: str | None
    amount: float
    status: str
    due_date: date
    issued_at: date | None
    paid_at: date | None
    notes: str | None
    created_at: datetime

    @classmethod
    def from_model(cls, row) -> "InvoiceType":
        return cls(
            id=strawberry.ID(str(row.id)),
            company_id=strawberry.ID(str(row.company_id)),
            project_id=strawberry.ID(str(row.project_id)) if row.project_id else None,
            invoice_number=row.invoice_number,
            amount=float(row.amount),
            status=row.status,
            due_date=row.due_date,
            issued_at=row.issued_at,
            paid_at=row.paid_at,
            notes=row.notes,
            created_at=row.created_at,
        )

    @strawberry.field
    async def currency(self, info: Info) -> str:
        # Invoices don't carry their own currency. If the invoice is tied to
        # a specific project, use that project's currency; otherwise fall
        # back to the client's projects, defaulting to GBP if there are none.
        if self.project_id is not None and info.context.db is not None:
            from app.db.models.project import Project

            project = await info.context.db.get(Project, UUID(str(self.project_id)))
            if project is not None:
                return project.currency

        loader = get_projects_by_company_loader(info.context)
        projects = await loader.load(UUID(str(self.company_id)))
        return projects[0].currency if projects else Currency.GBP.value


@strawberry.type
class InvoiceQuery:
    @strawberry.field
    async def invoices(
        self,
        info: Info,
        company_id: strawberry.ID | None = None,
        project_id: strawberry.ID | None = None,
        status: str | None = None,
    ) -> list[InvoiceType]:
        ctx = require_role(info.context, "admin", "project_manager")
        rows = await get_invoices(
            ctx.db,
            company_id=UUID(str(company_id)) if company_id else None,
            project_id=UUID(str(project_id)) if project_id else None,
            status=status,
        )
        return [InvoiceType.from_model(r) for r in rows]

    @strawberry.field
    async def invoice(self, info: Info, id: strawberry.ID) -> InvoiceType | None:
        ctx = require_role(info.context, "admin", "project_manager")
        try:
            row = await get_invoice_by_id(ctx.db, UUID(str(id)))
            return InvoiceType.from_model(row)
        except NotFoundError:
            return None


@strawberry.type
class InvoiceMutation:
    @strawberry.mutation
    async def create_invoice(
        self,
        info: Info,
        company_id: strawberry.ID,
        amount: float,
        due_date: date,
        project_id: strawberry.ID | None = None,
        invoice_number: str | None = None,
        status: str = "draft",
        issued_at: date | None = None,
        notes: str | None = None,
    ) -> InvoiceType:
        ctx = require_role(info.context, "admin", "project_manager")
        try:
            row = await create_invoice_record(
                ctx.db,
                actor=ctx.user,
                company_id=UUID(str(company_id)),
                amount=amount,
                due_date=due_date,
                project_id=UUID(str(project_id)) if project_id else None,
                invoice_number=invoice_number,
                status=status,
                issued_at=issued_at,
                notes=notes,
            )
            return InvoiceType.from_model(row)
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def update_invoice(
        self,
        info: Info,
        id: strawberry.ID,
        amount: float | None = None,
        due_date: date | None = None,
        status: str | None = None,
        invoice_number: str | None = None,
        issued_at: date | None = None,
        paid_at: date | None = None,
        notes: str | None = None,
    ) -> InvoiceType:
        ctx = require_role(info.context, "admin", "project_manager")
        try:
            row = await update_invoice_record(
                ctx.db,
                actor=ctx.user,
                invoice_id=UUID(str(id)),
                amount=amount,
                due_date=due_date,
                status=status,
                invoice_number=invoice_number,
                issued_at=issued_at,
                paid_at=paid_at,
                notes=notes,
            )
            return InvoiceType.from_model(row)
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def delete_invoice(self, info: Info, id: strawberry.ID) -> bool:
        ctx = require_role(info.context, "admin", "project_manager")
        try:
            return await delete_invoice_record(ctx.db, actor=ctx.user, invoice_id=UUID(str(id)))
        except Exception as exc:
            _gql_error(exc)
