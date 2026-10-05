# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@AGENTS.md

`AGENTS.md` is the canonical portable repository contract and applies to every
agent runtime, including Claude Code. `ads/SKILL.md` is the product entrypoint
(the `/ads` skill). Read order and operating rules live in `AGENTS.md` — do not
duplicate them here.

## Commands

Set up the environment (CPython 3.11 or 3.12):

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/python -m pip install --require-hashes --only-binary=:all: -r requirements.lock
.venv/bin/python -m pip install --require-hashes --only-binary=:all: -r requirements-dev.lock
.venv/bin/python -m pip install --require-hashes --only-binary=:all: -r .github/requirements-schema-tests.lock
.venv/bin/python -m pip check
```

Run tests:

```bash
python -m pytest -q                        # full local suite
python -m pytest tests/core tests/release -v --tb=short   # fast CI-equivalent subset
python -m pytest tests/core/test_scoring_engine.py -v      # single file
python -m pytest tests/core/test_scoring_engine.py::test_name -v  # single test
```

Other focused checks:

```bash
python -m claude_ads_core --version
python -m claude_ads_core validate finding path/to/finding.json
python -m claude_ads_core status --root . --as-of YYYY-MM-DD
python -m claude_ads_core next --root . --as-of YYYY-MM-DD
python -m compileall -q claude_ads_core evals scripts tests   # syntax check (CI step)
bash -n install.sh uninstall.sh                               # shell syntax check
python scripts/release.py audit                                # repository/content audit (CI step)
python scripts/release.py gate ...                              # release gate (needs external signed inputs)
```

CI (`.github/workflows/ci.yml`) runs, in order: repository audit
(`scripts/release.py audit` + syntax checks), core tests
(`tests/core` + `tests/release`) across a Python matrix, the full suite
(`pytest tests`), a dependency vulnerability audit
(`scripts/audit_dependencies.py`), and an installer matrix across
ubuntu/macos/windows. There is no separate lint/format step — `scripts/release.py
audit` covers JSON/YAML/frontmatter/path/sensitive-content checks instead.

## Architecture

Claude Ads is a prompt-driven system (Markdown skills/agents consumed by an
LLM runtime) backed by a small dependency-free Python core
(`claude_ads_core/`) that does the parts that must be deterministic: contract
validation, scoring, and report rendering. The two halves communicate only
through versioned JSON contracts — the LLM conductor never computes a score
or renders a report itself; it shells out to `claude_ads_core` (via
`python -m claude_ads_core ...`) and treats the result as ground truth.

**Conductor/worker model.** `ads/SKILL.md` is the single conductor: it owns
scope, routing, policy, scoring invocation, and final artifact assembly.
`agents/*.md` are bounded workers (one per platform audit, plus
cross-cutting roles like `research-worker.md` and `skill-reviewer.md`) that
each return one schema-valid result object (`status`, findings, evidence,
contradictions). Workers never write the final report and never share a
filename with another worker's output — a run's artifacts live under
`.claude-ads/runs/<run-id>/` with an immutable manifest.

**`claude_ads_core/` responsibilities:**
- `contracts.py` / `workflow_contracts.py`: strict semantic validation for the
  v1 JSON contracts in `claude_ads_core/schemas/v1/*.schema.json` (account
  snapshot, finding, report bundle, run manifest, setup/brand/media-plan/
  creative-brief/generation/monitoring/experiment/mutation-plan artifacts).
  This hand-written validation exists so the CLI works without a JSON Schema
  library installed; the `.schema.json` files remain the portable contract.
- `scoring.py`: deterministic scoring engine (`score_account`,
  `score_portfolio`). Controls and category weights are loaded from
  `control-plane/manifests/control-registry.json` /
  `scoring-profiles.json`, never recomputed ad hoc. Health, evidence
  coverage, regulatory exposure, and opportunities are kept as separate
  numbers — never blended into one score.
- `adapters/`: read-only-by-default platform adapters (`base.py` defines the
  `Capability`/`AdapterCapabilities` protocol with `CapabilityMode` ranging
  `export-read` → `live-write`, and `CapabilityStatus` from `declared` to
  `live-verified`). `csv_export.py` and `native_export.py` normalize vendor
  exports into `AccountSnapshot`; `mappings_v1.py` holds the field mappings.
  A capability must be `implemented`/`fixture-verified`/`live-verified` (not
  just `declared`) before `writes_enabled` is true anywhere.
- `orchestration.py` / `workflow_models.py`: immutable run/task/result/gate
  packet shapes for file-backed orchestration; reruns require an explicit
  `supersedes` chain rather than overwriting prior output.
- `product_status.py`: implements `status`/`next` — derives repository
  maturity and "the one blocker to fix next" from the manifests below,
  offline and fail-closed.
- `reporting.py`: renders Markdown/HTML/PDF from one validated
  `ReportBundle` JSON — all three are views of the same artifact, never
  independently generated.
- `financial_catalog.py` / `financial_model.py`: the deterministic
  unit-economics engine behind `skills/ads-math`. The catalog table drives
  both the arithmetic and the formula text, and the `financial-model`
  validator rejects any formula that differs from it. Undefined metrics are
  null with a reason (making the artifact `partial`), never an error.
- `cli.py`: thin argparse wrapper over all of the above
  (`validate`, `score`, `portfolio`, `financial-model`, `status`, `next`,
  `render`/`report`, `ingest-export`).

**`control-plane/` is the non-code source of truth** that both the prompts and
the Python core defer to instead of hardcoding facts:
- `manifests/capability-manifest.json`: authoritative per-platform
  read/write capability state (what adapters can actually do right now), plus
  `workflow_capabilities` for cross-platform engines such as `financial-model`.
  Both `scripts/release.py` and `product_status.py` enforce exactly twelve
  platforms and the same evidence rules for both sections.
- `manifests/control-registry.json` + `scoring-profiles.json`: the full audit
  control catalog and which profiles are enabled for scoring. All twelve
  platform scoring profiles are currently **disabled** pending per-control
  evidence/weights/regression approval — the catalog is for discovery
  findings only until then.
- `manifests/source-ledger.json` / `claim-ledger.json`: evidence registry —
  "no source, no current platform claim" is enforced by requiring an entry
  here before a prompt or doc can assert a dated platform fact.
- `manifests/safety-policy.json`, `data-lifecycle-policy.json`,
  `orchestration-policy.json`, `maturity-status.json`: the policy inputs
  `product_status.py` and the skill prompts read instead of restating.
- `PRODUCT_BOUNDARIES.md`, `PUBLISHING_POLICY.md`, `RELEASE_REQUIREMENTS.md`:
  what the product promises, what is public vs. private, and every gate
  (testing, security, packaging, signed external review, CI) required before
  calling a release current. `scripts/release.py gate` evaluates these
  against externally supplied signed evidence and fails closed if anything
  is missing, stale, or unsigned — a repository-local template cannot
  satisfy it.

**Mutation safety is structural, not a convention.** Every adapter defaults
to read-only; `MutationDisabledError` is the explicit failure mode. A write
path requires, simultaneously: a tested+enabled capability for that exact
operation, explicit account/object IDs, a human-reviewable before/after diff,
owner approval within account-defined ceilings, an idempotency key + audit +
rollback + verification window, and post-write remote-state verification.
Permanent deletion is out of scope for v2 and is refused even on explicit
request (see `ads/SKILL.md` canonical hard-stop examples).

**Evidence and staleness are tracked, not assumed.** Platform/policy claims
carry a source ID, retrieval date, confidence, and `refresh_due` date. Once
`refresh_due` has passed, the skill must reverify or demote the claim to
provisional — tool unavailability is never treated as license to keep using
stale evidence as current.

## Repository map

```
ads/                  the /ads orchestrating skill (entrypoint) and shared references
skills/               focused per-platform and per-workflow skills (ads-google, ads-meta, ads-audit, ...)
agents/               bounded worker prompts (one per platform audit, plus research/review workers)
claude_ads_core/      dependency-free deterministic engine: contracts, adapters, scoring, orchestration, reporting, CLI
control-plane/        evidence ledgers, capability/scoring/safety manifests, release-gate policy and schemas
scripts/              release packaging/gating, dependency auditing, browser/image/report helpers
evals/                routing and model-behavior eval cases (JSON contracts + gate scripts)
tests/                mirrors the above: core/, release/, routing/, scripts/, audit/, references/
```

## Development and verification notes

- Keep skill entrypoints concise and use progressive disclosure — load a
  reference or sub-skill only when the task routes to it, not by default.
- Keep platform facts and other volatile guidance in dated references
  (`control-plane/manifests/*`), not hardcoded into root instructions.
- Python tools should expose a CLI, structured (JSON) output, and tests
  proportional to risk — follow `claude_ads_core/cli.py`'s existing shape.
- Use manifest-derived counts and capability status in any claim about what
  the product supports; do not hand-maintain a count that could drift from
  `control-plane/manifests/capability-manifest.json`.
- Run the focused tests for the changed surface first, then the complete
  local suite, before claiming a change is verified. A release claim
  additionally requires every gate in
  `control-plane/RELEASE_REQUIREMENTS.md` plus required remote CI — neither
  is satisfied by local tests alone.
