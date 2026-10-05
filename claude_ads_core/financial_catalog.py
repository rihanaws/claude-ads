"""Input and metric catalog shared by the financial-model engine and validator (no package imports)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

InputKind = Literal["money", "count", "rate"]
Operation = Literal["divide", "multiply", "subtract", "reciprocal"]
MetricUnit = Literal["currency", "percent", "ratio", "rate", "months"]

_SYMBOLS = {"divide": "/", "multiply": "*", "subtract": "-"}


@dataclass(frozen=True)
class InputSpec:
    id: str
    kind: InputKind


@dataclass(frozen=True)
class MetricSpec:
    id: str
    operation: Operation
    operands: tuple[str, ...]
    unit: MetricUnit
    scale: int = 1
    requires_positive_margin: str | None = None

    @property
    def formula(self) -> str:
        if self.operation == "reciprocal":
            text = f"1 / {self.operands[0]}"
        else:
            left, right = self.operands
            text = f"{left} {_SYMBOLS[self.operation]} {right}"
        return text if self.scale == 1 else f"{text} * {self.scale}"


INPUTS: tuple[InputSpec, ...] = (
    InputSpec("spend", "money"),
    InputSpec("platform_revenue", "money"),
    InputSpec("business_revenue", "money"),
    InputSpec("total_marketing_spend", "money"),
    InputSpec("customer_lifetime_value", "money"),
    InputSpec("monthly_revenue_per_customer", "money"),
    InputSpec("impressions", "count"),
    InputSpec("clicks", "count"),
    InputSpec("conversions", "count"),
    InputSpec("leads", "count"),
    InputSpec("orders", "count"),
    InputSpec("new_customers", "count"),
    InputSpec("gross_margin_rate", "rate"),
    InputSpec("variable_cost_rate", "rate"),
)

# Dependency order: a metric operand is an input or an earlier metric.
METRICS: tuple[MetricSpec, ...] = (
    MetricSpec("cpa", "divide", ("spend", "conversions"), "currency"),
    MetricSpec("cpl", "divide", ("spend", "leads"), "currency"),
    MetricSpec("cpc", "divide", ("spend", "clicks"), "currency"),
    MetricSpec("cpm", "divide", ("spend", "impressions"), "currency", 1000),
    MetricSpec("ctr", "divide", ("clicks", "impressions"), "percent", 100),
    MetricSpec("cvr", "divide", ("conversions", "clicks"), "percent", 100),
    MetricSpec("aov", "divide", ("platform_revenue", "orders"), "currency"),
    MetricSpec("roas", "divide", ("platform_revenue", "spend"), "ratio"),
    MetricSpec("mer", "divide", ("business_revenue", "total_marketing_spend"), "ratio"),
    MetricSpec("contribution_margin_rate", "subtract", ("gross_margin_rate", "variable_cost_rate"), "rate"),
    MetricSpec("break_even_roas", "reciprocal", ("contribution_margin_rate",), "ratio"),
    MetricSpec(
        "break_even_cpa",
        "multiply",
        ("aov", "contribution_margin_rate"),
        "currency",
        requires_positive_margin="contribution_margin_rate",
    ),
    MetricSpec("cac", "divide", ("total_marketing_spend", "new_customers"), "currency"),
    MetricSpec("ltv_cac", "divide", ("customer_lifetime_value", "cac"), "ratio"),
    MetricSpec(
        "monthly_contribution_per_customer",
        "multiply",
        ("monthly_revenue_per_customer", "contribution_margin_rate"),
        "currency",
    ),
    MetricSpec("cac_payback_months", "divide", ("cac", "monthly_contribution_per_customer"), "months"),
)

INPUT_KINDS: dict[str, InputKind] = {spec.id: spec.kind for spec in INPUTS}
METRICS_BY_ID: dict[str, MetricSpec] = {spec.id: spec for spec in METRICS}
