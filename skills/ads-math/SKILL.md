---
name: ads-math
description: "Calculate and model paid-media CPA, CPL, CPC, CPM, ROAS, MER, break-even targets, contribution margin, LTV:CAC, impression-share opportunity, budgets, forecasts, and experiment economics. Use for PPC math, ad calculator, break-even analysis, ROAS calculator, CPA calculator, budget forecast, LTV CAC, or MER."
---

# Paid Media Financial Model

Never compute these metrics in the prompt. The deterministic engine owns the
arithmetic, the formula text, and the undefined-value rules.

1. Identify the decision and collect units, currency, period, tax/refund treatment,
   margin, attribution basis, and uncertainty.
2. Build a `financial-model` input envelope: `schema_version`, `artifact_type`,
   `run_id`, `created_at`, one `currency`, `period`, `requested_metrics`, `inputs`,
   `scenarios` (`base` first with no overrides, optional `downside` and `upside`
   overrides), `assumptions`, and `data_lifecycle`.
3. Map every input to an operator value or cited artifact. Omit unknown inputs;
   never fabricate, default, or zero-fill them. Money and counts are non-negative;
   `gross_margin_rate` and `variable_cost_rate` are fractions from 0 to 1.
4. Run `python -m claude_ads_core financial-model <input.json> >
   .claude-ads/runs/<run-id>/financial-model.json`, then
   `python -m claude_ads_core validate financial-model
   .claude-ads/runs/<run-id>/financial-model.json`. Never overwrite a prior run.
5. Report each metric with its emitted formula, scenario, and value. Report every
   null metric with its `undefined_reason`; a `partial` model is not complete.
6. Keep platform-attributed revenue (`platform_revenue`, ROAS) separate from blended
   business revenue (`business_revenue`, MER), cash flow, and contribution margin.

## Catalog

- Costs: `cpa` (per conversion), `cpl`, `cpc`, `cpm`, `cac` (blended: total
  marketing spend per new customer).
- Rates: `ctr` and `cvr` as percent; `contribution_margin_rate` as a fraction.
- Revenue: `aov` (platform revenue per order), `roas`, `mer`.
- Thresholds: `break_even_roas`, `break_even_cpa` (maximum CPA at zero contribution);
  both are undefined when the contribution margin is not positive.
- Payback: `ltv_cac`, `monthly_contribution_per_customer`, `cac_payback_months`.

`customer_lifetime_value` must already be on a contribution-margin basis.
Forecasts, impression-share opportunity, and experiment sizing are not in the
engine yet: label any such estimate provisional, show its formula and
assumptions, and never present a point forecast without them.
