"""Country-aware plan catalogue and pricing region resolution."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.tenant_settings import tenant_country

PLAN_FREE = "free"
PLAN_STUDIO = "studio"
PLAN_ENTERPRISE = "enterprise"

PRICING_REGION_IN = "IN"
PRICING_REGION_SG = "SG"
PRICING_REGION_AU = "AU"

FY_DAYS = 365


@dataclass(frozen=True)
class PlanDefinition:
    monthly_credits: int
    max_users: int
    social_integration: bool
    email_integration: bool
    monthly_price: Decimal
    currency_code: str


def pricing_region_for_country(country_code: str | None) -> str:
    code = (country_code or "").strip().upper()
    if code == PRICING_REGION_IN:
        return PRICING_REGION_IN
    if code == PRICING_REGION_AU:
        return PRICING_REGION_AU
    return PRICING_REGION_SG


def region_currency(region: str) -> str:
    return {"IN": "INR", "SG": "SGD", "AU": "AUD"}.get(region, "SGD")


def topup_factor_key(region: str) -> str:
    return {"IN": "topup_factor_in", "SG": "topup_factor_sg", "AU": "topup_factor_au"}.get(
        region, "topup_factor_sg"
    )


_PLANS: dict[str, dict[str, PlanDefinition]] = {
    PRICING_REGION_IN: {
        PLAN_FREE: PlanDefinition(
            monthly_credits=50,
            max_users=1,
            social_integration=False,
            email_integration=False,
            monthly_price=Decimal("0"),
            currency_code="INR",
        ),
        PLAN_STUDIO: PlanDefinition(
            monthly_credits=5000,
            max_users=3,
            social_integration=True,
            email_integration=True,
            monthly_price=Decimal("5000"),
            currency_code="INR",
        ),
        PLAN_ENTERPRISE: PlanDefinition(
            monthly_credits=0,
            max_users=999,
            social_integration=True,
            email_integration=True,
            monthly_price=Decimal("0"),
            currency_code="INR",
        ),
    },
    PRICING_REGION_SG: {
        PLAN_FREE: PlanDefinition(
            monthly_credits=50,
            max_users=1,
            social_integration=False,
            email_integration=False,
            monthly_price=Decimal("0"),
            currency_code="SGD",
        ),
        PLAN_STUDIO: PlanDefinition(
            monthly_credits=500,
            max_users=3,
            social_integration=True,
            email_integration=True,
            monthly_price=Decimal("50"),
            currency_code="SGD",
        ),
        PLAN_ENTERPRISE: PlanDefinition(
            monthly_credits=0,
            max_users=999,
            social_integration=True,
            email_integration=True,
            monthly_price=Decimal("0"),
            currency_code="SGD",
        ),
    },
    PRICING_REGION_AU: {
        PLAN_FREE: PlanDefinition(
            monthly_credits=50,
            max_users=1,
            social_integration=False,
            email_integration=False,
            monthly_price=Decimal("0"),
            currency_code="AUD",
        ),
        PLAN_STUDIO: PlanDefinition(
            monthly_credits=250,
            max_users=3,
            social_integration=True,
            email_integration=True,
            monthly_price=Decimal("50"),
            currency_code="AUD",
        ),
        PLAN_ENTERPRISE: PlanDefinition(
            monthly_credits=0,
            max_users=999,
            social_integration=True,
            email_integration=True,
            monthly_price=Decimal("0"),
            currency_code="AUD",
        ),
    },
}


def plan_definition(
    *,
    country_code: str | None,
    plan: str,
) -> PlanDefinition:
    region = pricing_region_for_country(country_code)
    normalized = (plan or PLAN_FREE).strip().lower()
    region_plans = _PLANS[region]
    if normalized not in region_plans:
        normalized = PLAN_FREE
    return region_plans[normalized]


def monthly_credits_for_plan(
    *,
    country_code: str | None,
    plan: str,
    enterprise_monthly_credits: int | None = None,
) -> int:
    normalized = (plan or PLAN_FREE).strip().lower()
    if normalized == PLAN_ENTERPRISE:
        return max(0, int(enterprise_monthly_credits or 0))
    return plan_definition(country_code=country_code, plan=normalized).monthly_credits


def tenant_pricing_region(tenant) -> str:
    return pricing_region_for_country(tenant_country(tenant))


def list_country_plans(*, country_code: str | None) -> list[dict[str, object]]:
    """Public plan catalogue for a country (server-side source of truth)."""
    region = pricing_region_for_country(country_code)
    currency = region_currency(region)
    plans: list[dict[str, object]] = []
    for code in (PLAN_FREE, PLAN_STUDIO, PLAN_ENTERPRISE):
        definition = _PLANS[region][code]
        plans.append(
            {
                "plan_code": code,
                "region": region,
                "currency_code": currency,
                "monthly_credits": definition.monthly_credits,
                "max_users": definition.max_users,
                "social_integration": definition.social_integration,
                "email_integration": definition.email_integration,
                "monthly_price": float(definition.monthly_price),
                "credits_per_page": 5,
            }
        )
    return plans
