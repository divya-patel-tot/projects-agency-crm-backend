from __future__ import annotations

import strawberry
from strawberry.types import Info

from app.core.deps import require_authenticated
from app.db.enums import UserRole
from app.graphql.companies.schema import CompanyType, company_from_model
from app.graphql.contacts.schema import ContactType
from app.graphql.planning.schema import TaskType
from app.graphql.projects.schema import ProjectType
from app.graphql.search.service import search_workspace

EMPTY_QUERY_MIN_LENGTH = 2


@strawberry.type
class SearchResultsType:
    companies: list[CompanyType]
    companies_count: int
    contacts: list[ContactType]
    contacts_count: int
    projects: list[ProjectType]
    projects_count: int
    tasks: list[TaskType]
    tasks_count: int


def _empty_results() -> SearchResultsType:
    return SearchResultsType(
        companies=[],
        companies_count=0,
        contacts=[],
        contacts_count=0,
        projects=[],
        projects_count=0,
        tasks=[],
        tasks_count=0,
    )


@strawberry.type
class SearchQuery:
    @strawberry.field(description="One search across companies, contacts, projects and tasks.")
    async def search(self, info: Info, query: str) -> SearchResultsType:
        ctx = require_authenticated(info.context)
        cleaned = query.strip()
        if len(cleaned) < EMPTY_QUERY_MIN_LENGTH:
            return _empty_results()

        member_user_id = ctx.user.id if ctx.user.role == UserRole.TEAM_MEMBER.value else None
        result = await search_workspace(ctx.db, query=cleaned, member_user_id=member_user_id)
        return SearchResultsType(
            companies=[company_from_model(row) for row in result.companies],
            companies_count=result.companies_count,
            contacts=[ContactType.from_model(row) for row in result.contacts],
            contacts_count=result.contacts_count,
            projects=[ProjectType.from_model(row) for row in result.projects],
            projects_count=result.projects_count,
            tasks=[TaskType.from_model(row) for row in result.tasks],
            tasks_count=result.tasks_count,
        )
