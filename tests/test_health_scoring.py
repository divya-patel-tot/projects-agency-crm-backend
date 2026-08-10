"""Health scoring invariants — touchpoints excluded, legacy weights folded."""

from app.graphql.org_settings import health_settings_from_dict


def test_default_weights_sum_to_one_without_touchpoints():
    settings = health_settings_from_dict({})
    total = (
        settings.weight_project_health
        + settings.weight_change_requests
        + settings.weight_contract
        + settings.weight_company_status
    )
    assert settings.weight_touchpoints == 0.0
    assert abs(total - 1.0) < 0.001


def test_legacy_touchpoint_weight_folds_into_project_health():
    settings = health_settings_from_dict(
        {
            "health_weight_project_health": 0.35,
            "health_weight_touchpoints": 0.25,
            "health_weight_change_requests": 0.15,
            "health_weight_contract": 0.15,
            "health_weight_company_status": 0.10,
        }
    )
    assert settings.weight_touchpoints == 0.0
    assert settings.weight_project_health == 0.60
    total = (
        settings.weight_project_health
        + settings.weight_change_requests
        + settings.weight_contract
        + settings.weight_company_status
    )
    assert abs(total - 1.0) < 0.001
