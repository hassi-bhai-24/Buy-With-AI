"""Standalone deterministic calculators (no LLM, no scraping)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..rate_limit import rate_limit
from ..schemas.request import (
    BrandMarkupRequest,
    ConvertLandRequest,
    CurrencyConvertRequest,
    DiscountValidatorRequest,
    ExpenseLeakageRequest,
    InstallmentAuditRequest,
    MarginRequest,
    SavingsGoalRequest,
)
from ..schemas.response import BrandMarkupAudit
from ..services import integrations
from ..services.calculators import discount_validator, expense_leakage, savings_goal
from ..services.rules import audit_installment_plan, convert_land

router = APIRouter()


class MarginOut(BaseModel):
    gross_profit_per_unit: float
    gross_margin_percent: float
    total_profit: float
    break_even_units: float | None


@router.post("/tools/margin", response_model=MarginOut)
async def margin(payload: MarginRequest, _limited: None = Depends(rate_limit)) -> MarginOut:
    gross_per_unit = payload.selling_price - payload.cost_per_unit
    margin_pct = (
        gross_per_unit / payload.selling_price * 100.0 if payload.selling_price else 0.0
    )
    total_profit = gross_per_unit * payload.quantity - payload.fixed_costs
    break_even = (
        payload.fixed_costs / gross_per_unit if gross_per_unit > 0 else None
    )
    return MarginOut(
        gross_profit_per_unit=round(gross_per_unit, 2),
        gross_margin_percent=round(margin_pct, 2),
        total_profit=round(total_profit, 2),
        break_even_units=round(break_even, 2) if break_even is not None else None,
    )


class ConvertLandOut(BaseModel):
    value: float
    from_unit: str
    to_unit: str
    marla_standard: str
    converted_value: float


@router.post("/tools/convert-land", response_model=ConvertLandOut)
async def convert_land_endpoint(payload: ConvertLandRequest, _limited: None = Depends(rate_limit)) -> ConvertLandOut:
    try:
        converted = convert_land(
            payload.value, payload.from_unit, payload.to_unit, payload.marla_standard
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ConvertLandOut(
        value=payload.value,
        from_unit=payload.from_unit,
        to_unit=payload.to_unit,
        marla_standard=payload.marla_standard,
        converted_value=round(converted, 4),
    )


class InstallmentAuditOut(BaseModel):
    cash_price: float
    total_paid: float
    finance_charge: float
    markup_percent: float
    # Legacy constant-ratio approximation; kept with its existing
    # meaning (see rules.audit_installment_plan / NOTES.md).
    apr_percent: float
    # Primary rate: cash-flow IRR as an effective annual rate.
    effective_annual_rate_percent: float
    apr_method: str
    markup_over_35_percent: bool


@router.post("/tools/installment-audit", response_model=InstallmentAuditOut)
async def installment_audit(payload: InstallmentAuditRequest, _limited: None = Depends(rate_limit)) -> InstallmentAuditOut:
    try:
        audit = audit_installment_plan(
            payload.cash_price,
            payload.down_payment,
            payload.monthly_installment,
            payload.months,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return InstallmentAuditOut(
        cash_price=audit.cash_price,
        total_paid=round(audit.total_paid, 2),
        finance_charge=round(audit.finance_charge, 2),
        markup_percent=round(audit.markup_percent, 2),
        apr_percent=round(audit.apr_percent, 2),
        effective_annual_rate_percent=round(
            audit.effective_annual_rate_percent, 2
        ),
        apr_method=audit.apr_method,
        markup_over_35_percent=audit.markup_percent > 35,
    )


class SavingsGoalOut(BaseModel):
    monthly_deposit_required: float
    months_required: int
    target_amount: float
    current_savings: float
    shortfall: float
    feasible: bool


@router.post("/tools/savings-goal", response_model=SavingsGoalOut)
async def savings_goal_endpoint(payload: SavingsGoalRequest, _limited: None = Depends(rate_limit)) -> SavingsGoalOut:
    try:
        return SavingsGoalOut(
            **savings_goal(
                payload.target_amount,
                payload.current_savings,
                payload.monthly_deposit,
                payload.months,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class ExpenseLeakageOut(BaseModel):
    income: float
    total_expenses: float
    essential_total: float
    discretionary_total: float
    discretionary_percent: float
    savings_rate_percent: float
    flags: list[str]
    notes: str


@router.post("/tools/expense-leakage", response_model=ExpenseLeakageOut)
async def expense_leakage_endpoint(
    payload: ExpenseLeakageRequest,
    _limited: None = Depends(rate_limit),
) -> ExpenseLeakageOut:
    return ExpenseLeakageOut(
        **expense_leakage(payload.income, payload.expenses)
    )


class CurrencyConvertOut(BaseModel):
    amount: float
    from_currency: str
    to_currency: str
    converted_amount: float
    rate: float
    rate_date: str | None
    source: str


@router.post("/tools/currency-convert", response_model=CurrencyConvertOut)
async def currency_convert_endpoint(
    payload: CurrencyConvertRequest,
    _limited: None = Depends(rate_limit),
) -> CurrencyConvertOut:
    try:
        result = await integrations.convert_currency(
            payload.amount, payload.from_currency, payload.to_currency
        )
    except integrations.UpstreamError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Currency service unavailable (Frankfurter): {exc}",
        ) from exc
    return CurrencyConvertOut(**result)


class DiscountValidatorOut(BaseModel):
    claimed_discount_percent: float
    real_discount_percent: float
    fake_discount: bool
    inflated_original: bool
    verdict_text: str


@router.post("/tools/discount-validator", response_model=DiscountValidatorOut)
async def discount_validator_endpoint(
    payload: DiscountValidatorRequest,
    _limited: None = Depends(rate_limit),
) -> DiscountValidatorOut:
    try:
        return DiscountValidatorOut(
            **discount_validator(
                payload.advertised_price,
                payload.claimed_original_price,
                payload.baseline_price,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/tools/brand-markup", response_model=BrandMarkupAudit)
async def brand_markup(payload: BrandMarkupRequest, _limited: None = Depends(rate_limit)) -> BrandMarkupAudit:
    if payload.making_cost is not None:
        making = payload.making_cost
        notes = "Calculated from the supplied making cost."
    else:
        making = payload.retail_price * 0.2
        notes = "Rough estimate, not a measured BOM."
    markup_pct = (
        (payload.retail_price - making) / making * 100.0 if making else 0.0
    )
    return BrandMarkupAudit(
        estimated_making_cost=round(making, 2),
        retail_asking_price=payload.retail_price,
        markup_percentage=round(markup_pct, 2),
        notes=notes,
    )
