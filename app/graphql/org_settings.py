"""Organization settings helpers with sensible defaults."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HealthOrgSettings:
    weight_project_health: float = 0.35
    weight_touchpoints: float = 0.25
    weight_change_requests: float = 0.15
    weight_contract: float = 0.15
    weight_company_status: float = 0.10
    at_risk_threshold: float = 60.0
    contract_renewal_window_days: int = 60


def health_settings_from_dict(settings: dict | None) -> HealthOrgSettings:
    raw = settings or {}
    return HealthOrgSettings(
        weight_project_health=float(raw.get("health_weight_project_health", 0.35)),
        weight_touchpoints=float(raw.get("health_weight_touchpoints", 0.25)),
        weight_change_requests=float(raw.get("health_weight_change_requests", 0.15)),
        weight_contract=float(raw.get("health_weight_contract", 0.15)),
        weight_company_status=float(raw.get("health_weight_company_status", 0.10)),
        at_risk_threshold=float(raw.get("health_at_risk_threshold", 60.0)),
        contract_renewal_window_days=int(raw.get("contract_renewal_window_days", 60)),
    )
