import strawberry
from strawberry.extensions import QueryDepthLimiter
from strawberry.tools import merge_types

from app.graphql.auth.schema import AuthMutation
from app.graphql.change_requests.schema import ChangeRequestMutation, ChangeRequestQuery
from app.graphql.companies.schema import CompanyMutation, CompanyQuery
from app.graphql.contacts.schema import ContactMutation, ContactQuery
from app.graphql.contracts.schema import ContractMutation, ContractQuery
from app.graphql.health.schema import HealthQuery
from app.graphql.planning.schema import PlanningMutation, PlanningQuery
from app.graphql.portal.auth.schema import PortalAuthMutation
from app.graphql.portal.schema import ApprovalMutation, DocumentMutation, DocumentQuery, PortalQuery
from app.graphql.projects.schema import ProjectMutation, ProjectQuery
from app.graphql.retention.schema import RetentionMutation, RetentionQuery
from app.graphql.tags.schema import TagMutation, TagQuery


@strawberry.type
class StatusQuery:
    @strawberry.field(description="API health probe for GraphQL.")
    def status(self) -> str:
        return "ok"


Query = merge_types(
    "Query",
    (
        StatusQuery,
        CompanyQuery,
        ContactQuery,
        TagQuery,
        ProjectQuery,
        PlanningQuery,
        PortalQuery,
        DocumentQuery,
        ChangeRequestQuery,
        RetentionQuery,
        HealthQuery,
        ContractQuery,
    ),
)

Mutation = merge_types(
    "Mutation",
    (
        AuthMutation,
        PortalAuthMutation,
        CompanyMutation,
        ContactMutation,
        TagMutation,
        ProjectMutation,
        PlanningMutation,
        ApprovalMutation,
        DocumentMutation,
        ChangeRequestMutation,
        RetentionMutation,
        ContractMutation,
    ),
)

schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
    extensions=[lambda: QueryDepthLimiter(max_depth=10)],
)
