import strawberry
from graphql import GraphQLError
from strawberry.types import Info

from app.core.deps import require_role
from app.core.exceptions import DomainError
from app.db.models.organization import Organization
from app.graphql.change_requests.state_machine import org_settings_from_dict
from app.graphql.org_settings import health_settings_from_dict

WEIGHT_SUM_TOLERANCE = 0.01


def _gql_error(exc: Exception) -> None:
    if isinstance(exc, DomainError):
        raise GraphQLError(exc.message, extensions={"code": exc.code}) from exc
    raise exc


@strawberry.type
class OrgSettingsType:
    health_weight_project_health: float
    health_weight_touchpoints: float
    health_weight_change_requests: float
    health_weight_contract: float
    health_weight_company_status: float
    health_at_risk_threshold: float
    contract_renewal_window_days: int
    cr_internal_approval_cost_threshold: float
    cr_internal_approval_timeline_days_threshold: int
    cr_revision_cap: int
    cr_response_sla_days: int

    @classmethod
    def from_org(cls, org: Organization) -> "OrgSettingsType":
        raw = org.settings or {}
        health = health_settings_from_dict(raw)
        cr = org_settings_from_dict(raw)
        return cls(
            health_weight_project_health=health.weight_project_health,
            health_weight_touchpoints=health.weight_touchpoints,
            health_weight_change_requests=health.weight_change_requests,
            health_weight_contract=health.weight_contract,
            health_weight_company_status=health.weight_company_status,
            health_at_risk_threshold=health.at_risk_threshold,
            contract_renewal_window_days=health.contract_renewal_window_days,
            cr_internal_approval_cost_threshold=cr.internal_cost_threshold,
            cr_internal_approval_timeline_days_threshold=cr.internal_timeline_days_threshold,
            cr_revision_cap=cr.revision_cap,
            cr_response_sla_days=cr.response_sla_days,
        )


@strawberry.type
class OrganizationQuery:
    @strawberry.field
    async def organization_settings(self, info: Info) -> OrgSettingsType:
        ctx = require_role(info.context, "admin")
        org = await ctx.db.get(Organization, ctx.user.org_id)
        return OrgSettingsType.from_org(org)


@strawberry.type
class OrganizationMutation:
    @strawberry.mutation
    async def update_organization_settings(
        self,
        info: Info,
        health_weight_project_health: float | None = None,
        health_weight_touchpoints: float | None = None,
        health_weight_change_requests: float | None = None,
        health_weight_contract: float | None = None,
        health_weight_company_status: float | None = None,
        health_at_risk_threshold: float | None = None,
        contract_renewal_window_days: int | None = None,
        cr_internal_approval_cost_threshold: float | None = None,
        cr_internal_approval_timeline_days_threshold: int | None = None,
        cr_revision_cap: int | None = None,
        cr_response_sla_days: int | None = None,
    ) -> OrgSettingsType:
        ctx = require_role(info.context, "admin")
        try:
            org = await ctx.db.get(Organization, ctx.user.org_id)
            current = dict(org.settings or {})

            updates = {
                "health_weight_project_health": health_weight_project_health,
                "health_weight_touchpoints": health_weight_touchpoints,
                "health_weight_change_requests": health_weight_change_requests,
                "health_weight_contract": health_weight_contract,
                "health_weight_company_status": health_weight_company_status,
                "health_at_risk_threshold": health_at_risk_threshold,
                "contract_renewal_window_days": contract_renewal_window_days,
                "cr_internal_approval_cost_threshold": cr_internal_approval_cost_threshold,
                "cr_internal_approval_timeline_days_threshold": cr_internal_approval_timeline_days_threshold,
                "cr_revision_cap": cr_revision_cap,
                "cr_response_sla_days": cr_response_sla_days,
            }
            for key, value in updates.items():
                if value is not None:
                    current[key] = value

            weight_keys = [
                "health_weight_project_health",
                "health_weight_touchpoints",
                "health_weight_change_requests",
                "health_weight_contract",
                "health_weight_company_status",
            ]
            if any(updates[key] is not None for key in weight_keys):
                total = sum(float(current.get(key, 0)) for key in weight_keys)
                if abs(total - 1.0) > WEIGHT_SUM_TOLERANCE:
                    raise DomainError(
                        f"The five health weights must add up to 1.0 (currently {total:.2f}).",
                        code="bad_user_input",
                    )

            org.settings = current
            await ctx.db.flush()
            return OrgSettingsType.from_org(org)
        except Exception as exc:
            _gql_error(exc)
