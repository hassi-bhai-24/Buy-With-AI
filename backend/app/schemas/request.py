"""Request schemas: analyze + standalone tool calculators."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from .common import CurrencyEnum, Location
from .response import CategoryEnum


class AnalyzeRequest(BaseModel):
    """One purchase check.

    ``asking_price`` is the TOTAL asking price for ``quantity`` units of
    the item (for a single item, quantity=1, so it is just the price).
    Per-unit prices are derived as asking_price / quantity.
    """

    description: str = Field(min_length=3, max_length=2000)
    title: Optional[str] = Field(default=None, max_length=255)
    category: CategoryEnum = CategoryEnum.OTHER
    asking_price: float = Field(ge=0)
    currency: CurrencyEnum = CurrencyEnum.PKR
    quantity: float = Field(default=1, gt=0)
    unit: str = Field(default="unit", max_length=32)
    location: Location = Field(default_factory=Location)
    days_to_sell: int = Field(default=7, ge=1, le=365)
    # days_to_sell is the time horizon for perishable/inventory
    # calculations: hours_to_sell = days_to_sell * 24. There is no
    # second time field; transit/selling time is this horizon.
    temperature_c: Optional[float] = Field(default=None, ge=-10, le=55)
    # Fraction of the lot damaged in transit, 0..0.9. When absent the
    # current 0.10 default is used and recorded as an assumption.
    # No lambda override is offered: lambda is a temperature-tiered
    # spec heuristic (see rules.lambda_for_temperature); overriding
    # it directly would obscure the model.
    transit_damage_percent: Optional[float] = Field(default=None, ge=0, le=0.9)
    seller_notes: str = Field(default="", max_length=2000)
    selling_price: Optional[float] = Field(default=None, ge=0)
    private_mode: bool = False
    # Local device identity ONLY — NOT secure authentication. Anyone
    # who knows a device UUID can read that device's history; there
    # is no password, token, or ownership check on it.
    device_uuid: Optional[str] = Field(default=None, max_length=64)
    # Optional installment terms, used for the installment-markup rule.
    down_payment: Optional[float] = Field(default=None, ge=0)
    monthly_installment: Optional[float] = Field(default=None, ge=0)
    installment_months: Optional[int] = Field(default=None, ge=1, le=120)
    # Optional property fields; also parsed from the description when absent.
    area_marla: Optional[float] = Field(default=None, gt=0)
    marla_standard: str = Field(default="225", max_length=16)

    @field_validator("marla_standard")
    @classmethod
    def _marla_standard_known(cls, value: str) -> str:
        allowed = {
            "225", "punjab_225", "urban", "urban_scheme",
            "272", "lahore_272", "punjab_272", "272.25", "revenue",
        }
        if value.strip().lower() not in allowed:
            raise ValueError(f"unknown marla_standard: {value}")
        return value.strip().lower()


class JournalCreateRequest(BaseModel):
    check_id: str = Field(min_length=1, max_length=36)
    original_asking_price: Optional[float] = Field(default=None, ge=0)
    final_negotiated_price: float = Field(ge=0)
    deal_status: str = Field(default="Purchased", max_length=32)
    outcome_notes: Optional[str] = Field(default=None, max_length=2000)


class MarginRequest(BaseModel):
    cost_per_unit: float = Field(ge=0)
    selling_price: float = Field(ge=0)
    fixed_costs: float = Field(default=0, ge=0)
    quantity: float = Field(default=1, gt=0)


class ConvertLandRequest(BaseModel):
    value: float = Field(ge=0)
    from_unit: str = Field(max_length=16)
    to_unit: str = Field(max_length=16)
    marla_standard: str = Field(default="225", max_length=16)

    @field_validator("marla_standard")
    @classmethod
    def _marla_standard_known(cls, value: str) -> str:
        allowed = {
            "225", "punjab_225", "urban", "urban_scheme",
            "272", "lahore_272", "punjab_272", "272.25", "revenue",
        }
        if value.strip().lower() not in allowed:
            raise ValueError(f"unknown marla_standard: {value}")
        return value.strip().lower()


class InstallmentAuditRequest(BaseModel):
    cash_price: float = Field(gt=0)
    down_payment: float = Field(ge=0)
    monthly_installment: float = Field(ge=0)
    months: int = Field(ge=1, le=120)


class BrandMarkupRequest(BaseModel):
    retail_price: float = Field(ge=0)
    making_cost: Optional[float] = Field(default=None, ge=0)


class SavingsGoalRequest(BaseModel):
    """TOOL-2: interest-free savings timeline. No interest rate is used."""

    target_amount: float = Field(gt=0)
    current_savings: float = Field(default=0, ge=0)
    monthly_deposit: Optional[float] = Field(default=None, gt=0)
    months: Optional[int] = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _at_least_one_timeline_input(self) -> "SavingsGoalRequest":
        if self.monthly_deposit is None and self.months is None:
            raise ValueError(
                "Provide at least one of monthly_deposit or months."
            )
        return self


class ExpenseItem(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    amount: float = Field(ge=0)
    category: str = Field(min_length=1, max_length=64)


class ExpenseLeakageRequest(BaseModel):
    """TOOL-3: income must be > 0; expenses may be empty."""

    income: float = Field(gt=0)
    expenses: list[ExpenseItem] = Field(default_factory=list)


class CurrencyConvertRequest(BaseModel):
    """TOOL-5: currency codes are validated as 3-letter alpha only.

    Any 3-letter code is accepted locally; unknown codes are rejected
    by Frankfurter and surfaced as a 502 (no currency list is invented).
    """

    amount: float = Field(ge=0)
    from_currency: str = Field(min_length=3, max_length=3)
    to_currency: str = Field(min_length=3, max_length=3)

    @field_validator("from_currency", "to_currency")
    @classmethod
    def _three_letter_alpha_upper(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) != 3 or not cleaned.isalpha():
            raise ValueError("currency code must be exactly 3 letters")
        return cleaned.upper()


class DiscountValidatorRequest(BaseModel):
    """TOOL-8: advertised must not exceed the claimed original price."""

    advertised_price: float = Field(gt=0)
    claimed_original_price: float = Field(gt=0)
    baseline_price: float = Field(gt=0)

    @model_validator(mode="after")
    def _advertised_not_above_claimed(self) -> "DiscountValidatorRequest":
        if self.advertised_price > self.claimed_original_price:
            raise ValueError(
                "advertised_price must not exceed claimed_original_price"
            )
        return self
