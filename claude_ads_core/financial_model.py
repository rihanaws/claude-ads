"""Deterministic paid-media financial model computed from the metric catalog."""

from __future__ import annotations

import copy
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Mapping

from .contracts import ContractError, validate_contract
from .financial_catalog import METRICS, METRICS_BY_ID, MetricSpec
from .workflow_contracts import WorkflowContractError, validate_financial_model_input

OUTPUT_QUANTUM = Decimal("0.0001")
MAX_OUTPUT_MAGNITUDE = Decimal("1e15")

Evaluation = tuple[Decimal | None, str | None]


class FinancialModelError(ValueError):
    """Raised when a financial-model input is invalid or the output fails its contract."""


def _evaluate_metric(
    spec: MetricSpec,
    inputs: Mapping[str, Decimal],
    metrics: Mapping[str, Evaluation],
) -> Evaluation:
    operands: list[Decimal] = []
    for ref in spec.operands:
        if ref in METRICS_BY_ID:
            value = metrics[ref][0]
            if value is None:
                return None, f"upstream_undefined:{ref}"
        else:
            value = inputs.get(ref)
            if value is None:
                return None, f"missing_input:{ref}"
        operands.append(value)

    margin_ref = spec.requires_positive_margin
    if margin_ref is not None and operands[spec.operands.index(margin_ref)] <= 0:
        return None, f"non_positive_margin:{margin_ref}"
    if spec.operation in {"divide", "reciprocal"}:
        denominator, denominator_ref = operands[-1], spec.operands[-1]
        if denominator == 0:
            return None, f"zero_denominator:{denominator_ref}"
        if denominator < 0:
            return None, f"negative_denominator:{denominator_ref}"
        numerator = operands[0] if spec.operation == "divide" else Decimal(1)
        value = numerator / denominator
    elif spec.operation == "multiply":
        value = operands[0] * operands[1]
    else:
        value = operands[0] - operands[1]
    return value * spec.scale, None


def _evaluate(inputs: Mapping[str, Any]) -> dict[str, Evaluation]:
    decimals = {key: Decimal(str(value)) for key, value in inputs.items()}
    metrics: dict[str, Evaluation] = {}
    for spec in METRICS:
        metrics[spec.id] = _evaluate_metric(spec, decimals, metrics)
    return metrics


def _output_value(metric_id: str, value: Decimal) -> float:
    if abs(value) >= MAX_OUTPUT_MAGNITUDE:
        raise FinancialModelError(f"{metric_id} exceeds the supported output magnitude")
    rounded = value.quantize(OUTPUT_QUANTUM, rounding=ROUND_HALF_UP)
    return 0.0 if rounded == 0 else float(rounded)


def evaluate_financial_model(payload: Any) -> dict[str, Any]:
    """Compute requested metrics per scenario; undefined metrics become null and mark the artifact partial."""

    try:
        validate_financial_model_input(payload)
    except WorkflowContractError as exc:
        raise FinancialModelError(str(exc)) from exc

    artifact = copy.deepcopy(dict(payload))
    results: list[dict[str, Any]] = []
    undefined = False
    for scenario in artifact["scenarios"]:
        effective = {**artifact["inputs"], **scenario["overrides"]}
        evaluated = _evaluate(effective)
        metrics: list[dict[str, Any]] = []
        for metric_id in artifact["requested_metrics"]:
            spec = METRICS_BY_ID[metric_id]
            value, reason = evaluated[metric_id]
            undefined = undefined or value is None
            metrics.append(
                {
                    "id": metric_id,
                    "formula": spec.formula,
                    "input_refs": list(spec.operands),
                    "unit": spec.unit,
                    "value": None if value is None else _output_value(metric_id, value),
                    "undefined_reason": reason,
                }
            )
        results.append({"scenario_id": scenario["id"], "inputs": effective, "metrics": metrics})

    artifact["status"] = "partial" if undefined else "complete"
    artifact["results"] = results
    try:
        validate_contract("financial-model", artifact)
    except ContractError as exc:
        raise FinancialModelError(f"self-check failed: {exc}") from exc
    return artifact
