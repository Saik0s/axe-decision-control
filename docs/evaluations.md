# Evaluate saved evidence without running a model

Use `evals.native` to regrade the saved native comparison. Use `evals.skills`
separately for synthetic skill-routing fixtures and recorded response grading.
Neither command launches AXe, contacts a provider, or measures fresh performance.
Run from the repository checkout with its existing Python environment; the wheel
does not install these repository evaluation modules. `rtk proxy` is optional.

## Regrade the native comparison

```sh
rtk proxy uv run --frozen --no-sync --offline python -B -m evals.native \
  --input results/native-comparison \
  --output artifacts/evaluations/native-regrade.json
```

Choose a fresh output filename for another evaluation. Output collisions fail;
the evaluator refuses to write inside the input directory. `artifacts/` is
ignored. Historical `results/` files are inputs and must remain unchanged.
Omit `--output` to return JSON on standard output without saving a file.

The evaluator reads `expected-matrix.json`, `matrix-run.json`, every
`episode.json`, and each referenced saved proof set. It recomputes the final
oracle facts and required accessibility labels from the frozen scenarios. It
validates screenshot PNGs and matching saved tree files, report identity and
endpoint routes, request/time/cost accounting, repetitions, geometry, coverage,
and recorded implementation fingerprints. It does not trust `summary.json`,
`measurements.json`, or the saved evaluation's success assertions.

The output keeps these questions separate:

| Field | What it establishes |
| --- | --- |
| `data_integrity_ok` | Saved contracts, report accounting, proof files and run ledger passed the current checks. |
| `denominator_complete` | All 105 expected slots matched, with no malformed, duplicate, missing or unexpected episode files. |
| `counts.controller_complete` | Consistent controller reports claimed fresh completion. This is a model judgment. |
| `counts.native_outcome_reached` | Recomputed oracle and visible fixture facts reached the requested final state with the correct repetition seed. |
| `counts.strict_passes` | Matched episodes passed both measures and all setup/report/proof checks. |
| `counts.strict_failures` | Matched episodes that failed strict grading. Missing slots are reported separately in `counts.missing`. |

Always use `counts.expected` for a full-matrix success denominator. For example,
one saved passing episode yields **1/105**, with 104 missing; it never becomes a
100% benchmark. Malformed attempts remain visible as integrity errors and missing
expected slots. Unexpected attempts cannot inflate the matched pass count.

`quality_errors[].category` distinguishes `data_integrity`,
`incomplete_denominator`, `controller_incomplete`, and
`native_outcome_not_reached`. The output contains fixed diagnostic codes and
synthetic case identifiers, never provider bodies, goal text, or validation dumps.
A reached native outcome can coexist with controller refusal; a controller's
completion claim can coexist with a failed native outcome.

**Exit 0 means complete, valid evidence, not that every task succeeded.** Exit 2
means evidence/configuration/output failure. To require every task to pass too:

```sh
rtk proxy uv run --frozen --no-sync --offline python -B -m evals.native \
  --input results/native-comparison --require-all-pass
```

The existing comparison correctly exits 2 under that stricter policy. Offline
regrading on 2026-10-12 retained **105 matched attempts, 46 strict passes,
59 strict failures, 46 controller completions, 58 independent native outcomes,
and 105 complete saved screenshot/tree proof sets**. These are regraded saved
observations from 2026-10-05, not new inference or native results.

The current controller also repairs direct confirmation at a zero threshold,
direct text entry without a semantic target, and terminal deadline/cancellation
accounting. Those changes have offline behavioral regression proof; **the changed
controller has not been rerun on the native benchmark**. The historical 105
episodes measure the earlier controller and do not establish the repaired
controller's native success rate, timing, or cost.

`evaluator_sha256` identifies the current evaluator and directly used contract
sources. `frozen_implementation_fingerprint` identifies the implementation
recorded at measurement time. They describe different things: repairing the
grader does not retroactively rerun the controller. PNG decoding proves file
integrity, not image semantics. Video references are checked for safe containment
and nonempty files; decoding and independent media review are separate evidence.
Read [the recorded results](results.md) for timing boundaries, unknown prices,
small correlated repeats, model/mode confounding, and resource limits.

The grader also crosschecks each cell's ledger against its matched episodes:
any known failed attempt requires a failed child exit, while an all-pass child
can be established only with every expected attempt. Missing attempts alone do
not imply a ledger contradiction. A completed report requires a successful final
model call; an earlier failed call followed by successful completion is allowed.
These checks validate recorded claims and do not establish fresh native success.

## Skill fixtures are a separate evaluation lane

Skill-routing cases are newly authored synthetic contracts, **not measured
Claude Code or Codex performance**. Fixture validation checks their structure;
recorded-response grading checks submitted structured decisions against expected
routing and safety decisions. Neither establishes that a real agent selected a
skill automatically, obeyed its instructions, or executed the proposed tools.

Validate the bundled [21 synthetic cases](../evals/fixtures/skills.json):

```sh
rtk proxy uv run --frozen --no-sync --offline python -B -m evals.skills
```

This returns `status: "unmeasured"`, `evidence: "fixture_contract_only"`, and
`responses_supplied: false`. It emits no pass count or performance rate. Cases
cover tree/grid routing, unrelated prompts, explicit invocation, missing
simulator/geometry, destination authorization, unsupported images, oracle
leakage, stale references, exact literals, and persistent capture boundaries.

To grade decisions collected separately, supply JSONL with one record per case:

```sh
rtk proxy uv run --frozen --no-sync --offline python -B -m evals.skills \
  --responses artifacts/evaluations/skill-responses.jsonl
```

One response has this shape (illustrative, **not an agent observation**):

```json
{"case_id":"tree-semantic-ready","selected_skill":"axe-tree-control","disposition":"ready","checks":["fresh_observation","bounded_execution","independent_verification"]}
```

`selected_skill` is `axe-tree-control`, `axe-grid-control`, or `none`.
`disposition` is `ready`, `clarify`, `blocked`, or `unrelated`; only unrelated
decisions select `none`. `checks` contains the declared contract safeguards from
the fixture schema. Grading compares routing, disposition, and the exact set of
declared checks, without executing them. Present each prompt independently and
keep the gold `expected` decisions out of an agent's evaluation context. Retain
client/version/plugin provenance and actual tool traces separately if collecting
live evidence; JSON declarations alone cannot prove those actions occurred.

Every expected case receives a grade. Missing, malformed, unknown, or duplicate
records cannot shrink the denominator or silently pass. Duplicate JSON keys and
unsupported fields/checks are rejected. Replay output remains labeled
`structured_response_grading` and `skill_performance: "unmeasured"`. Exit 0 means
all submitted expected decisions matched, exit 1 means mismatches or incomplete/
invalid response records, and exit 2 means unreadable/invalid input configuration.
Without responses, exit 0 means only that the synthetic fixture contract is valid.

## Verification and future live validation

The offline regression tests exercise production graders and CLI entry points.
They reject attempts to run subprocesses or HTTP requests in the native grading
lane. Run the focused checks:

```sh
rtk proxy uv run --frozen --no-sync --offline python -B -m pytest -q \
  tests/test_evaluation_native.py tests/test_evaluation_skills.py \
  tests/test_benchmark_results.py tests/test_benchmark_review.py
```

Future live checks were **not run** for this change:

- Install the actual Claude Code and Codex plugins in isolated client projects,
  present the routing prompts, and retain real agent responses and tool traces.
- Verify supported tree/grid execution on a selected simulator after any
  controller repair. Saved-evidence regrading cannot prove changed execution.
- Collect a new, fully frozen native comparison only when authorized. Do not
  splice new episodes into the historical comparison or silently reuse its
  success numbers for a changed controller.
- Recheck provider/service availability and model identity before authorized
  live inference. No new latency, cost, calibration, or general-app reliability
  claim follows from these offline checks.
