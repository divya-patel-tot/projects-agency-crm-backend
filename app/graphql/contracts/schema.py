from datetime import date, datetime
from uuid import UUID

import strawberry
from graphql import GraphQLError
from strawberry.types import Info

from app.core.deps import require_authenticated, require_role
from app.core.exceptions import DomainError, NotFoundError
from app.graphql.contracts.service import (
    create_contract_record,
    delete_contract_record,
    get_contract_by_id,
    get_contracts,
    update_contract_record,
)


def _gql_error(exc: Exception) -> None:
    if isinstance(exc, (DomainError, NotFoundError)):
        raise GraphQLError(exc.message, extensions={"code": exc.code}) from exc
    raise exc


@strawberry.type
class ContractType:
    id: strawberry.ID
    company_id: strawberry.ID
    name: str
    start_date: date
    end_date: date
    value: float | None
    auto_renew: bool
    status: str

    @classmethod
    def from_model(cls, row) -> "ContractType":
        return cls(
            id=strawberry.ID(str(row.id)),
            company_id=strawberry.ID(str(row.company_id)),
            name=row.name,
            start_date=row.start_date,
            end_date=row.end_date,
            value=float(row.value) if row.value is not None else None,
            auto_renew=row.auto_renew,
            status=row.status,
        )


@strawberry.type
class ContractQuery:
    @strawberry.field
    async def contracts(
        self,
        info: Info,
        company_id: strawberry.ID | None = None,
        status: str | None = None,
    ) -> list[ContractType]:
        ctx = require_authenticated(info.context)
        rows = await get_contracts(
            ctx.db,
            company_id=UUID(str(company_id)) if company_id else None,
            status=status,
        )
        return [ContractType.from_model(r) for r in rows]

    @strawberry.field
    async def contract(self, info: Info, id: strawberry.ID) -> ContractType | None:
        ctx = require_authenticated(info.context)
        try:
            row = await get_contract_by_id(ctx.db, UUID(str(id)))
            return ContractType.from_model(row)
        except NotFoundError:
            return None


@strawberry.type
class ContractMutation:
    @strawberry.mutation
    async def create_contract(
        self,
        info: Info,
        company_id: strawberry.ID,
        name: str,
        start_date: date,
        end_date: date,
        value: float | None = None,
        auto_renew: bool = False,
        status: str = "draft",
    ) -> ContractType:
        ctx = require_role(info.context, "admin", "finance_admin")
        try:
            row = await create_contract_record(
                ctx.db,
                actor=ctx.user,
                company_id=UUID(str(company_id)),
                name=name,
                start_date=start_date,
                end_date=end_date,
                value=value,
                auto_renew=auto_renew,
                status=status,
            )
            return ContractType.from_model(row)
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def update_contract(
        self,
        info: Info,
        id: strawberry.ID,
        name: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        value: float | None = None,
        auto_renew: bool | None = None,
        status: str | None = None,
    ) -> ContractType:
        ctx = require_role(info.context, "admin", "finance_admin")
        try:
            row = await update_contract_record(
                ctx.db,
                actor=ctx.user,
                contract_id=UUID(str(id)),
                name=name,
                start_date=start_date,
                end_date=end_date,
                value=value,
                auto_renew=auto_renew,
                status=status,
            )
            return ContractType.from_model(row)
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def delete_contract(self, info: Info, id: strawberry.ID) -> bool:
        ctx = require_role(info.context, "admin", "finance_admin")
        try:
            return await delete_contract_record(ctx.db, actor=ctx.user, contract_id=UUID(str(id)))
        except Exception as exc:
            _gql_error(exc)
