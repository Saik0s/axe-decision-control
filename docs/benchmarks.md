# FocusBench benchmark harness

The harness compares bounded agents on five synthetic FocusBench scenarios with
three matched repetitions by default. Success requires a completed, consistent
CLI report, exact fixture state, visible final facts, and saved screenshot/tree
proof. A model's completion judgment alone cannot pass an episode.

The final matrix has seven valid provider/model/mode cells, five scenarios and
three matched repetitions, **105 episodes**. The [recorded results](results.md)
retain all 105 attempts, valid saved proof and matched before/after fingerprints.
Quality failures remain in the denominator; a complete matrix is not a claim
that every controller reached its goal.
The portable matrix CLI freezes expected coverage before starting any child run;
its offline checks do not establish native benchmark results.

## Prepare a portable checkout

Run commands from the repository root, wherever it is cloned. The wheel installs
`axe-control` and `axe_control`, not `benchmarks` or the FocusBench fixture; keep
the checkout for benchmark execution. `rtk proxy` is optional, so omit that
prefix if RTK is absent. Prepare Python 3.12+ and the checkout dependencies once:

```sh
rtk proxy uv sync --frozen
```

Subsequent `uv run --no-sync --offline` commands use that environment without
updating the lock file or downloading dependencies. `--offline` applies to uv,
not to model requests or native actions during benchmark execution. The harness
starts `axe-control` by name; uv exposes the checkout environment's executable
on PATH.
AXe and Xcode's `xcrun` must also be on PATH. Native runs require macOS, a selected
full Xcode installation with an iOS Simulator SDK/runtime, a compatible AXe,
and one already booted, dedicated test simulator. The fixture builder targets
iOS 17.0+ on an arm64 or x86_64 Mac; actual build/runtime compatibility still
depends on the selected Xcode and installed simulator runtime.

Build the synthetic app before freezing a new matrix:

```sh
rtk proxy uv run --no-sync --offline python fixtures/FocusBench/build.py \
  --output benchmark-runs/fixture-build
```

This compiles and ad hoc signs `benchmark-runs/fixture-build/FocusBench.app`;
it does not install or launch the app. Use a different build directory if this
one belongs to an active run. Do not rebuild or change the selected app,
implementation, lock file, or environment during a frozen matrix.

Set `BENCH_APP` to that app directory (or another already built FocusBench.app),
`BENCH_UDID` to the chosen simulator's explicit UUID, and `BENCH_POINTS` to its
actual logical `WIDTHxHEIGHT`. Screenshot pixels are a different unit; the
default `402x874` is suitable only when the selected simulator matches it.
Set `BENCH_OUTPUT` to a **new, nonexistent directory** under `benchmark-runs/`
for each invocation, including previews and single-cell runs. Relative app and
output paths are resolved from the repository root.

Check native video capture before using `--record`. CoreSimulator may deny a
recording destination even when ordinary file writes work there. In this host's
capture probe, an external APFS destination returned Cocoa error513 / OSStatus
-12204; a local destination recorded successfully. Use a local output directory
if that occurs. Start a short capture below and stop it with Ctrl-C; this records
the selected simulator but does not act on the app:

```sh
rtk proxy xcrun simctl io "${BENCH_UDID:?Select the test simulator}" \
  recordVideo --codec=h264 benchmark-runs/capture-probe.mp4
```

Choose a new probe filename and ensure its parent exists. A setup or capture
failure is an environment result, not evidence of model task performance.

Before the full matrix, select a running Winnow service that supports text
decisions, image decisions with its matching projector, and native function
calls. Set `BENCH_WINNOW_MODEL` to its actual model ID, `BENCH_WINNOW_URL` to its
base URL, and `BENCH_SIMULATOR_RUNTIME` to an explicit runtime label. Configure
OpenRouter credentials as described in [usage](usage.md#provider-and-credentials).
Services, model weights, credentials, and simulator setup are external
prerequisites. The full matrix sends synthetic tasks to hosted providers as
well as Winnow and may incur provider charges. For local inference measurements
without simulator control, use the separate [local performance](local-performance.md)
guide and supply your own running service address and PID.

## Run the frozen final matrix

Finish source edits first and reserve the fixture simulator and model server
for the comparison. With the prerequisites above satisfied:

```sh
rtk proxy uv run --no-sync --offline python -m benchmarks.matrix \
  --udid "${BENCH_UDID:?Select one booted test simulator}" \
  --app "${BENCH_APP:?Supply the built FocusBench.app directory}" \
  --points "${BENCH_POINTS:?Supply logical WIDTHxHEIGHT}" \
  --winnow-model "${BENCH_WINNOW_MODEL:?Supply the served model ID}" \
  --winnow-url "${BENCH_WINNOW_URL:?Supply the selected service base URL}" \
  --simulator-runtime "${BENCH_SIMULATOR_RUNTIME:?Supply the runtime label}" \
  --output "${BENCH_OUTPUT:?Choose a new directory under benchmark-runs}" --record
```

Set `BENCH_WINNOW_MODEL` to the actual server's model ID, `BENCH_WINNOW_URL` to its
safe base URL, and `BENCH_SIMULATOR_RUNTIME` to an explicit label such as
`iOS 27.0 simulator`. The runtime label is an operator declaration, not an
automatic native probe. Optionally add
`--server-pid "${BENCH_SERVER_PID:?Select the Winnow server PID}"` for process
sampling; it applies only to Winnow cells. The default example requires no PID.
Keys follow the existing CLI environment configuration and inherit silently;
there is no key argument. Child stdout/stderr are discarded.

The seven cells are:

- `gpt-direct`: OpenRouter `openai/gpt-4.1-mini`, direct.
- `clef-tree`, `clef-grid`: OpenRouter `cloudflare/clef`, tree and grid.
- `jev-tree`: OpenRouter `typesafe/jev-1.13`, tree.
- `winnow-direct`, `winnow-tree`, `winnow-grid`: the explicitly selected Winnow
  model, direct, tree and grid.

OpenRouter defaults to `https://openrouter.ai/api`; Winnow defaults to
`http://127.0.0.1:8091`. `--openrouter-url` and `--winnow-url` can override these.
Geometry defaults to `402x874`, and shared budgets to 300 seconds, 20 steps and
120 requests. Use `--points`, `--max-seconds`, `--max-steps`, and `--max-requests`
to change them consistently. The manifest must have exactly the five IDs
`basic`, `duration`, `quiet-off`, `prefilled`, and `scroll`. Full scenario
definitions are frozen; changing a goal or initial/expected state is detectable.
The final matrix fixes three repetitions and does not accept unsupported pairs.

The output root must be new. `expected-matrix.json` freezes the complete scenario
definitions, cells, budgets, geometry and implementation/runtime snapshot before
native execution. `matrix-run.json` records pending, running and finished/failed
cells and is replaced atomically after each transition. Every child invokes the
existing `benchmarks.run` sequentially with its own fresh cell root. Setup and
agent failures remain episodes; launch failures remain cell records and missing
coverage. A nonzero child exit or a child timeout does not skip later cells.

SIGINT/SIGTERM cancels the matrix and interrupts the active child, giving it up
to 45 seconds to finalize evidence before forced termination. Later cells stay
pending. An additional per-cell watchdog allows
`15 * (max_seconds + 120) + 120` seconds, **6,420 seconds** at default budgets.
The existing runner owns its CLI/native process cleanup. Ordinary failures
finish the matrix, then `summary.json` is written. Matrix exit 0 requires complete
coverage, all episodes passing, clean metadata, and every child finishing with
exit 0; any failure or cancellation returns 2. Hard interruption can leave the
previous ledger incomplete, but expectations already exist for a later audit.

Snapshots contain SHA-256 hashes of Python implementation, fixture Swift source,
the bundled scenario manifest, `pyproject.toml`, `uv.lock`, the imported runtime
package, and supplied app files. They also retain Python version, system/machine,
dependency versions and the declared simulator runtime. Absolute paths,
environment values, keys and child command lines are not stored. Snapshots are
checked before and after each cell against the frozen snapshot; changes make
coverage unfit for a frozen-implementation comparison while later cells continue.
These boundary checks do not prove that an external server or UI stayed unchanged
throughout a cell; provider telemetry and the separate inference lane remain
necessary for those claims.

`--plan-only` writes the frozen expectation and pending ledger without starting
children. It still requires a readable built app and the prepared Python
environment for fingerprinting. It makes no native or provider requests and
does not require credentials or a running service. It is a preview, not a
resumable run: use another fresh root for actual execution. The matrix never
creates or boots a simulator or starts a model server; its native harness
installs, resets, and launches FocusBench on the selected simulator.

## Run one matrix cell

From the repository root, with the package installed and `axe-control`, `axe`,
Xcode's `xcrun`, and the already built FocusBench app available:

```sh
rtk proxy uv run --no-sync --offline python -m benchmarks.run \
  --udid "${BENCH_UDID:?Select one booted test simulator}" \
  --app "${BENCH_APP:?Supply the built FocusBench.app directory}" \
  --provider openrouter --model "${BENCH_MODEL:?Supply cloudflare/clef or typesafe/jev-1.13}" --mode tree \
  --base-url https://openrouter.ai/api \
  --repeats 3 --points "${BENCH_POINTS:?Supply logical WIDTHxHEIGHT}" \
  --scenarios benchmarks/scenarios.json \
  --max-seconds 300 --max-steps 20 --max-requests 120 \
  --output "${BENCH_OUTPUT:?Choose a new directory under benchmark-runs}" --record
```

Set `BENCH_MODEL` to `cloudflare/clef` or `typesafe/jev-1.13` for this tree example.
Set `BENCH_APP` to the previously built FocusBench.app directory.
`BENCH_UDID` must identify one existing, booted simulator. The harness never
creates, boots, erases, rotates, or reconfigures devices. It checks the supplied
app's FocusBench bundle ID/executable, then installs it once per invocation.
Use an isolated test simulator and only synthetic manifests. Capture is for
FocusBench; no private apps, account content, or credentials belong in this run.

For a local Winnow server, choose `--provider winnow`, its explicit `--model`,
and `--base-url http://127.0.0.1:8091`. Optionally add
`--server-pid "$BENCH_SERVER_PID"` for a known, explicitly selected server
process. Credentials follow the CLI's existing environment/key configuration;
do not put keys in arguments, manifests, URLs, or output paths. Base URLs with
userinfo, query parameters, or fragments are rejected.

Each matrix cell needs a **new output directory**. Reused directories are
rejected before simulator mutation, preventing stale report/evidence reuse.
The defaults are the bundled manifest, three repetitions, and 402 × 874 logical
points. Additional budget flags default to 300 seconds, 20 steps, 120 requests.
These bound the agent run; a harness watchdog allows 45 seconds for CLI startup
and teardown beyond the agent's own time budget, then sends SIGINT, waits up to
10 seconds, and kills an unresponsive CLI process group, including its native
command children.

## Matched reset and independent evaluation

Repetitions are numbered from zero. The launch seed is
`scenario.initial.seed + 1009 * repetition`, identical across matrix cells.
Before each episode the harness terminates FocusBench; a specific not-running
diagnostic is benign. It launches with explicit `--seed`, `--duration`, `--quiet`,
`--prefill`, and `--scroll`. Installation and reset failures remain failed
episodes, never skipped cases.

For up to 10 seconds after launch it checks the refreshed
`Documents/axe-benchmark-state.json` for phase `home`, initial name, duration,
quiet state, matched seed, and exact supplied screen width/height. It also
requires a fresh visible FocusBench accessibility label before starting the
agent. Geometry mismatch fails setup rather than silently changing the device.

The agent CLI receives the scenario goal, allowed text literals, supplied
geometry, provider selection, budgets, selected UDID, and report destination.
Oracle files, expected values, evaluator labels, and evaluator frames are never
passed to the planner. Its normal mode-specific observations remain unchanged.
All native commands use fixed argument arrays; model output never becomes shell
commands.

After the CLI exits, evaluation independently reads the final oracle and a
fresh AXe tree. It requires exact name, duration, quiet state, phase `running`,
seed, and geometry. The visible tree must contain `Session started`, the exact
name, `<duration> minutes`, and `Quiet mode on/off`. Conflicting quiet labels or
the fixture's state-write-error label fail evaluation. The summarizer recomputes
this evaluation instead of trusting a saved success flag.

## Artifacts and resource measurements

Each `<scenario>/repeat-<index>/` directory contains:

- `episode.json`: strict schema, scenario/repetition/seed, provider configuration,
  `RunReport` when available, independent evaluation, setup/proof failures,
  optional resource samples, and relative proof filenames.
- `run-report.json`: the CLI's strict content-free telemetry. Missing, malformed,
  or inconsistent reports fail the episode. Invalid reports are replaced with a
  fixed diagnostic; raw error bodies are not retained.
- `final.png` and `final-tree.json`: fresh screenshot plus an allowlisted tree of
  synthetic labels. Unknown labels are omitted and counted; raw AXe trees and
  control frames are not saved. Capture is withheld if FocusBench is not visible
  or initial fixture validation never succeeded.
- `original.mp4`, only with `--record` on the first manifest case, repetition
  zero. Native `simctl recordVideo --codec=h264` writes the original recording for
  the selected UDID. SIGINT finalizes it, with a 30-second encoding timeout.
  There is no resize, overlay, transcode, or synthetic replacement.

Wall/model seconds come from `RunReport`, excluding app setup and video
encoding. Native commands, failures, and actual AXe mutations are separate
counts; one agent action can issue several mutating commands.

Optional process sampling verifies the supplied PID and uses only
`ps -o rss=,pcpu= -p PID` every 100 milliseconds while the agent runs. Samples
retain elapsed sample time, RSS in KiB, and CPU percent. Peak RSS describes the
**whole process**, not a per-request allocation or Metal peak. CPU is `ps`
process utilization, **not calibrated energy**. A missing initial PID fails
setup. A later sampling error preserves prior samples and identifies partial
resource coverage; it does not replace the task evaluation. PID reuse and
sub-100ms peaks cannot be excluded by these observations.

Subprocess output is captured/discarded, never echoed as diagnostics. The
harness does not save environment values, command lines, credentials, raw HTTP
errors, or nonfixture content. Keep generated artifacts under ignored
`benchmark-runs/` paths.

## Summarize results

For a complete seven-cell matrix, generate the readable comparison and standalone
PNG/SVG figures without contacting a provider or controlling a simulator:

```sh
rtk proxy uv run --no-sync --with matplotlib python -m tools.report_native \
  --input "$BENCH_RESULTS" --output-dir "$BENCH_RESULTS"
```

`BENCH_RESULTS` selects the completed matrix directory. This example saves the
report beside its episode directories so relative media links work. Matplotlib
is optional and installed ephemerally
by uv. The reporter refuses incomplete coverage, changed fingerprints, invalid
proof or inconsistent reports. Model/task failures remain in all-attempt plots
and denominators. It reports successful wall medians separately from fast
refusals, and distinguishes controller passes from independent outcomes reached.
To curate a separate destination, copy the synthetic dataset there first, then
select that directory for both arguments. The reporter does not copy recordings.

```sh
rtk proxy uv run --no-sync --offline python -m benchmarks.summarize \
  "${BENCH_OUTPUT:?Select the completed single-cell output directory}" \
  --output "${BENCH_OUTPUT:?Select the completed single-cell output directory}/summary.json"
```

For the final matrix, summarize its root rather than the directory containing other
runs. `expected-matrix.json` is discovered automatically; it can also be selected
explicitly:

```sh
rtk proxy uv run --no-sync --offline python -m benchmarks.summarize \
  "${BENCH_OUTPUT:?Select the completed final matrix output directory}" \
  --expected "${BENCH_OUTPUT:?Select the completed final matrix output directory}/expected-matrix.json" \
  --output "${BENCH_OUTPUT:?Select the completed final matrix output directory}/summary.json"
```

Coverage lists expected/observed/matched counts, every missing slot and every
unexpected file. Matching requires the frozen full scenario, provider settings,
budgets, geometry, repetition 0–2 and the exact
`<cell>/<scenario>/repeat-<index>/episode.json` layout. Duplicate, malformed or
incompatible rows cannot fill missing slots. The ledger must match the frozen
expectation hash and its cell fingerprints; incomplete or changed metadata also
fails coverage. A one-episode interrupted matrix reports 104 missing slots and
exits 2. Episode failures and matrix coverage are separate: 105 present episodes
can have complete coverage while their outcomes fail.

Only files named `episode.json` are inputs. Results are stratified by the full
scenario definition, provider/model/mode/base URL/budgets, and geometry, so
incompatible tasks or budgets cannot silently merge. Each stratum reports
successes/failures, Wilson 95% success intervals, status/failure counts,
wall/model time sums, native/request counts, reported cost, and unpriced request
counts. `independent_outcome_successes` recomputes the embedded oracle/tree
outcome independently of model completion and saved files.
`saved_proof_complete` counts file validation separately; it is `null` for
in-memory aggregation without file inspection. This avoids an overall average
hiding scenario difficulty or an embedded outcome claiming saved evidence.

Proof references must be relative to their episode directory. Absolute paths,
`..` traversal, Windows-style paths and symlinks escaping that directory are
rejected before files are opened. A screenshot must be a nonempty valid PNG; a
tree must parse as strict `SyntheticTree`, contain labels and exactly match the
embedded final tree. A referenced video must be a nonempty regular file. An
unreferenced video is optional. These file checks establish reviewable artifacts,
not PNG authenticity, video decodability, or the video's final UI state; native
media review remains necessary. Missing/corrupt/unsafe proof adds
`proof_incomplete` and a media-specific reason while preserving the episode and
its embedded outcome in the denominator.

Every valid episode remains in its denominator, including setup failures and
missing or inconsistent CLI reports. Inconsistent reports are flagged and
excluded from numeric time/cost/command totals; their episodes still fail.
Known reported costs are summed; absent prices remain `null`, not zero. Partial
cost coverage remains visible in `unpriced_requests` and `missing_reports`.
Malformed files and repeated copies of the same scenario/repetition/configuration
are listed in `invalid_files`; duplicates do not inflate success counts. The
summary exits 2 when inputs are invalid, empty, or frozen coverage is incomplete,
otherwise 0 even if valid episodes failed. Without an expected matrix, coverage
is `null` and the summary makes no full-suite claim. The runner exits 0 only when
every episode passed, otherwise 2.

Results describe this synthetic fixture only. Model quality, mode, and model
identity are confounded by the chosen matrix. Do not claim a causal mode effect
or general application reliability. Wilson intervals assume independent episodes;
matched repeated tasks may be correlated, and three repetitions yield wide
intervals. Failures and unpriced calls must accompany comparisons.

## Local verification

```sh
rtk proxy uv run --no-sync --offline python -m pytest \
  tests/test_benchmark_review.py tests/test_benchmark_results.py
rtk proxy uv run --no-sync --offline ruff check benchmarks/run.py benchmarks/summarize.py \
  benchmarks/matrix.py benchmarks/resources.py \
  tests/test_benchmark_review.py tests/test_benchmark_results.py
rtk proxy env MYPYPATH=src:. uv run --no-sync --offline mypy --strict --namespace-packages \
  --explicit-package-bases benchmarks/run.py benchmarks/summarize.py \
  benchmarks/matrix.py benchmarks/resources.py \
  tests/test_benchmark_review.py tests/test_benchmark_results.py
```

These are schema, evaluator, real temporary PNG/tree file inspection, exact
105-slot coverage, and mocked harness/orchestration checks. Native
reset, AXe visibility, API execution, and original video validity need the
actual matrix execution and independent media review before reporting runtime
success. These checks require the development dependencies installed by the
default `uv sync --frozen` preparation step.
