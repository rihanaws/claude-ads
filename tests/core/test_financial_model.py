"""Deterministic financial-model engine, contract, and catalog tests."""

from __future__ import annotations

import copy
import json
import random
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from claude_ads_core.cli import main
from claude_ads_core.contracts import ContractError, validate_contract
from claude_ads_core.financial_catalog import INPUT_KINDS, INPUTS, METRICS, METRICS_BY_ID
from claude_ads_core.financial_model import FinancialModelError, evaluate_financial_model

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "financial-model"
MONEY_INPUTS = [spec.id for spec in INPUTS if spec.kind == "money"]


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _values(artifact: dict, scenario_id: str) -> dict:
    result = next(item for item in artifact["results"] if item["scenario_id"] == scenario_id)
    return {metric["id"]: metric["value"] for metric in result["metrics"]}


def _reasons(artifact: dict) -> dict:
    return {metric["id"]: metric["undefined_reason"] for metric in artifact["results"][0]["metrics"]}


@pytest.mark.parametrize("name", ["", "partial-"])
def test_golden_fixtures_are_reproduced_exactly(name):
    artifact = evaluate_financial_model(_load(f"{name}input.json"))
    assert artifact == _load(f"{name}expected.json")
    validate_contract("financial-model", artifact)


def test_hand_checked_unit_economics():
    artifact = evaluate_financial_model(_load("input.json"))
    assert artifact["status"] == "complete"
    base = _values(artifact, "base")
    assert base["cpa"] == 40.0
    assert base["cpm"] == 20.0
    assert base["ctr"] == 2.0
    assert base["roas"] == 3.0
    assert base["mer"] == 5.0
    assert base["contribution_margin_rate"] == 0.45
    assert base["break_even_roas"] == 2.2222
    assert base["break_even_cpa"] == 67.5
    assert base["ltv_cac"] == 6.0
    assert base["cac_payback_months"] == 4.4444
    downside = _values(artifact, "downside")
    assert downside["aov"] == 137.5
    assert downside["break_even_cpa"] == 55.0
    assert downside["cac_payback_months"] == 5.0
    assert _values(artifact, "upside")["cpa"] == 33.3333


def test_undefined_metrics_are_null_with_reasons_and_mark_partial():
    artifact = evaluate_financial_model(_load("partial-input.json"))
    assert artifact["status"] == "partial"
    assert _reasons(artifact) == {
        "cpc": "zero_denominator:clicks",
        "cvr": "zero_denominator:clicks",
        "cpl": "missing_input:leads",
        "roas": None,
        "contribution_margin_rate": None,
        "break_even_roas": "negative_denominator:contribution_margin_rate",
        "cac": "zero_denominator:new_customers",
        "ltv_cac": "upstream_undefined:cac",
    }


def test_unrequested_undefined_metrics_do_not_make_the_model_partial():
    payload = _load("partial-input.json")
    payload["requested_metrics"] = ["cpm", "roas"]
    artifact = evaluate_financial_model(payload)
    assert artifact["status"] == "complete"
    assert _values(artifact, "base") == {"cpm": 40.0, "roas": 0.0}


def test_scenario_overrides_do_not_leak_into_base():
    payload = _load("input.json")
    original = copy.deepcopy(payload)
    artifact = evaluate_financial_model(payload)
    assert payload == original
    assert artifact["results"][0]["inputs"] == payload["inputs"]
    assert artifact["results"][1]["inputs"]["conversions"] == 100


def _set_input(key: str, value):
    return lambda payload: payload["inputs"].__setitem__(key, value)


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(_set_input("spend", -1), id="negative-spend"),
        pytest.param(_set_input("clicks", True), id="bool-number"),
        pytest.param(_set_input("spend", float("nan")), id="nan"),
        pytest.param(_set_input("spend", 10**400), id="overflowing-integer"),
        pytest.param(_set_input("gross_margin_rate", 1.01), id="rate-above-one"),
        pytest.param(_set_input("leads", None), id="null-input"),
        pytest.param(_set_input("revenue", 10), id="unknown-input"),
        pytest.param(lambda p: p.update(currency="usd"), id="lowercase-currency"),
        pytest.param(lambda p: p["scenarios"][1]["overrides"].update(currency="EUR"), id="override-currency"),
        pytest.param(lambda p: p.update(scenarios=p["scenarios"][1:]), id="missing-base"),
        pytest.param(lambda p: p["scenarios"][0].update(overrides={"spend": 1}), id="base-overrides"),
        pytest.param(lambda p: p["scenarios"].append(copy.deepcopy(p["scenarios"][1])), id="duplicate-scenario"),
        pytest.param(lambda p: p.update(requested_metrics=[]), id="empty-metrics"),
        pytest.param(lambda p: p.update(requested_metrics=["profit"]), id="unknown-metric"),
        pytest.param(lambda p: p.update(period={"start": "2026-06-30", "end": "2026-06-01"}), id="reversed-period"),
        pytest.param(lambda p: p.update(status="complete"), id="already-computed"),
    ],
)
def test_structurally_invalid_input_is_rejected(change):
    payload = _load("input.json")
    change(payload)
    with pytest.raises(FinancialModelError):
        evaluate_financial_model(payload)


def test_non_positive_margin_makes_break_even_targets_undefined():
    payload = _load("input.json")
    payload["requested_metrics"] = ["break_even_roas", "break_even_cpa"]
    payload["inputs"]["variable_cost_rate"] = 0.6
    artifact = evaluate_financial_model(payload)
    assert _reasons(artifact) == {
        "break_even_roas": "zero_denominator:contribution_margin_rate",
        "break_even_cpa": "non_positive_margin:contribution_margin_rate",
    }


def test_rounded_negative_zero_is_emitted_as_zero():
    payload = _load("input.json")
    payload["requested_metrics"] = ["contribution_margin_rate"]
    payload["inputs"].update(gross_margin_rate=0.00001, variable_cost_rate=0.00002)
    value = _values(evaluate_financial_model(payload), "base")["contribution_margin_rate"]
    assert json.dumps(value) == "0.0"


def test_outputs_beyond_supported_magnitude_are_rejected():
    payload = _load("input.json")
    payload["inputs"]["impressions"] = 1e-12
    with pytest.raises(FinancialModelError, match="cpm exceeds the supported output magnitude"):
        evaluate_financial_model(payload)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda doc: doc["results"][0]["metrics"][0].update(formula="spend / orders"), "catalog formula"),
        (lambda doc: doc["results"][0]["metrics"][0].update(undefined_reason="missing_input:spend"), "must be null"),
        (lambda doc: doc["results"][0]["metrics"][0].update(value=None), "undefined_reason"),
        (lambda doc: doc.update(status="partial"), "partial exactly"),
        (lambda doc: doc["results"][1]["inputs"].update(conversions=1), "scenario overrides"),
        (lambda doc: doc["results"][0]["metrics"].reverse(), "requested_metrics in order"),
        (lambda doc: doc["results"].pop(), "one entry per scenario"),
    ],
)
def test_validator_rejects_tampered_artifacts(change, message):
    artifact = _load("expected.json")
    change(artifact)
    with pytest.raises(ContractError, match=message):
        validate_contract("financial-model", artifact)


def test_catalog_metrics_only_reference_inputs_or_earlier_metrics():
    assert len(METRICS_BY_ID) == len(METRICS)
    assert not set(INPUT_KINDS) & set(METRICS_BY_ID)
    seen: set[str] = set()
    for spec in METRICS:
        for operand in spec.operands:
            assert operand in INPUT_KINDS or operand in seen, (spec.id, operand)
        assert spec.requires_positive_margin in (None, *spec.operands), spec.id
        seen.add(spec.id)


def test_schema_enumerations_match_the_catalog(repo_root):
    schema = json.loads(
        (repo_root / "claude_ads_core/schemas/v1/financial-model.schema.json").read_text(encoding="utf-8")
    )
    assert schema["properties"]["requested_metrics"]["items"]["enum"] == [spec.id for spec in METRICS]
    assert schema["$defs"]["metric"]["properties"]["id"]["enum"] == [spec.id for spec in METRICS]
    input_properties = schema["$defs"]["inputs"]["properties"]
    assert set(input_properties) == set(INPUT_KINDS)
    for input_id, kind in INPUT_KINDS.items():
        assert ("maximum" in input_properties[input_id]) == (kind == "rate")


def test_engine_output_conforms_to_the_json_schema(repo_root):
    schema_root = repo_root / "claude_ads_core/schemas/v1"
    documents = [json.loads(path.read_text(encoding="utf-8")) for path in schema_root.glob("*.json")]
    registry = Registry().with_resources(
        (document["$id"], Resource.from_contents(document)) for document in documents
    )
    schema = json.loads((schema_root / "financial-model.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, registry=registry)
    for name in ("expected.json", "partial-expected.json"):
        assert not list(validator.iter_errors(_load(name))), name


def test_skill_names_every_catalog_metric(repo_root):
    skill = (repo_root / "skills/ads-math/SKILL.md").read_text(encoding="utf-8")
    for spec in METRICS:
        assert f"`{spec.id}`" in skill, spec.id


def _random_payload(rng: random.Random) -> dict:
    payload = _load("input.json")
    inputs: dict[str, float] = {}
    for input_id, kind in INPUT_KINDS.items():
        roll = rng.random()
        if roll < 0.1:
            continue
        if roll < 0.2:
            inputs[input_id] = 0
        elif kind == "rate":
            inputs[input_id] = round(rng.random(), 4)
        else:
            inputs[input_id] = round(rng.uniform(1, 100_000), 2)
    payload["inputs"] = inputs
    payload["scenarios"] = [{"id": "base", "overrides": {}}]
    return payload


def test_random_valid_inputs_always_produce_a_valid_deterministic_artifact():
    rng = random.Random(20261004)
    for _ in range(300):
        payload = _random_payload(rng)
        first = evaluate_financial_model(payload)
        assert json.dumps(first, sort_keys=True) == json.dumps(evaluate_financial_model(payload), sort_keys=True)
        validate_contract("financial-model", first)


def test_scaling_money_scales_cost_metrics_and_preserves_ratios():
    rng = random.Random(7)
    factor = 3
    for _ in range(100):
        payload = _load("input.json")
        payload["scenarios"] = [{"id": "base", "overrides": {}}]
        for input_id in MONEY_INPUTS:
            payload["inputs"][input_id] = rng.randint(1, 50_000)
        scaled = copy.deepcopy(payload)
        for input_id in MONEY_INPUTS:
            scaled["inputs"][input_id] = payload["inputs"][input_id] * factor
        before = _values(evaluate_financial_model(payload), "base")
        after = _values(evaluate_financial_model(scaled), "base")
        for metric_id in ("cpa", "cpc", "cpm", "aov", "cac"):
            assert after[metric_id] == pytest.approx(before[metric_id] * factor, abs=factor * 0.00005 + 1e-9)
        for metric_id in ("roas", "mer", "ctr", "ltv_cac", "cac_payback_months"):
            assert after[metric_id] == before[metric_id]


def test_break_even_roas_is_the_reciprocal_of_contribution_margin():
    rng = random.Random(11)
    for _ in range(200):
        payload = _load("input.json")
        payload["scenarios"] = [{"id": "base", "overrides": {}}]
        payload["inputs"]["gross_margin_rate"] = round(rng.uniform(0.2, 1), 4)
        payload["inputs"]["variable_cost_rate"] = round(rng.uniform(0, 0.19), 4)
        values = _values(evaluate_financial_model(payload), "base")
        assert values["break_even_roas"] * values["contribution_margin_rate"] == pytest.approx(1, abs=1e-3)


def test_cli_computes_validates_and_reports_errors(tmp_path, capsys):
    assert main(["financial-model", str(FIXTURES / "input.json")]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output == _load("expected.json")

    out_path = tmp_path / "model.json"
    out_path.write_text(json.dumps(output), encoding="utf-8")
    assert main(["validate", "financial-model", str(out_path)]) == 0
    capsys.readouterr()

    bad = _load("input.json")
    bad["inputs"]["spend"] = -5
    bad_path = tmp_path / "bad.json"
    bad_path.write_text(json.dumps(bad), encoding="utf-8")
    assert main(["financial-model", str(bad_path)]) == 2
    error = json.loads(capsys.readouterr().err)
    assert error["status"] == "invalid"
    assert "$.inputs.spend must be >= 0" in error["error"]
