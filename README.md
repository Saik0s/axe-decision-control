# AXe Decision Control

Bounded iOS Simulator control through AXe, as a Python library, CLI, and two
project skills. Keep your own goal and choose the observation method it needs.

**Status: implemented and measured on a synthetic native fixture.** The
CLI/library, provider adapters, two skills and benchmark harness are included.
All 320 tests, lint, strict typing and an independent wheel installation pass.
The frozen native comparison retains all **105 episodes**, including failures,
across seven model/mode pairs, five seeded scenarios and three repeats.

**Grid control is experimental: 0/30 strict benchmark passes.** It performed
native focus, text entry and taps, but visual grounding and completion judgments
were unreliable. Tree and direct modes also had failures. See the
[measured results](docs/results.md) for each model, original recordings, final
proof and all 66 local inference attempts. This is not general app accuracy.

## Install and run

Requires Python 3.12+, uv, macOS with Xcode, AXe on PATH, and an already selected,
booted iOS Simulator. Provider services, weights, and credentials are external.
The examples use `rtk proxy` for this workspace; omit that prefix if RTK is absent.
From this checkout, install the CLI:

```sh
rtk proxy uv tool install .
rtk proxy axe-control --help
```

Or run from the checkout without a tool installation. Supply `AXE_UDID` as one
explicit simulator UDID, `AXE_POINTS` as its logical `WIDTHxHEIGHT`, and `AXE_GOAL`
as the user's requested goal. `booted` is not an accepted UDID. This local example
requires a caller-managed Winnow service already serving the chosen model:

```sh
rtk proxy uv run axe-control run \
  --udid "${AXE_UDID:?Select one simulator}" \
  --points "${AXE_POINTS:?Supply logical WIDTHxHEIGHT}" \
  --goal "${AXE_GOAL:?Supply the user goal}" \
  --provider winnow --model Winnow-12B \
  --base-url "${WINNOW_BASE_URL:-http://127.0.0.1:8091}" --mode tree
```

Add a separate `--text "$AXE_TEXT"` for each exact, user-approved literal needed
for text entry. Do not infer or generate additional literals. A different service
address must be selected explicitly; a developer's temporary port is not a default.

## Choose a mode

| Mode | Model input and action selection | Provider |
| --- | --- | --- |
| `tree` | Accessibility state; typed choices of current semantic targets | OpenRouter Clef/Jev, or Winnow |
| `grid` | Screenshots and geometry; coarse then fine visual localization | Clef image route or vision-enabled Winnow; experimental grounding |
| `direct` | Accessibility state; one actual `simulator_action` function call | Generative OpenRouter model, or Winnow chat |

Tree prefers semantics. Grid converts screenshot pixels using the supplied logical
point size, with no universal 3x scaling. Jev accepts text decisions only and is
rejected for grid. Direct exposes bounded simulator actions, not host shell access.

Default limits are **20 steps, 120 model requests, and 300 seconds**. Time and
cancellation checks are cooperative: an in-flight request can finish after the
time budget, and cancellation prevents the next action rather than instantly
interrupting work. `completed` means a fresh model judgment; benchmark success
requires the independent oracle. Belief thresholds are uncalibrated control
settings, never permission to act.

## Library, CLI, and skills

- [Usage](docs/usage.md): exact commands, authentication, library example, capture,
  and completion semantics.
- [Architecture](docs/architecture.md): planner boundaries, budgets, and evidence.
- [Provider contracts](docs/provider-contracts.md): identity, wire formats, source
  citations, and unverified integrations.
- [Benchmarks](docs/benchmarks.md): native matrix, independent outcomes and saved proof.
- [Local performance](docs/local-performance.md): measured prefix-cold/warm workloads.
- [Measured results](docs/results.md): complete native comparison, local inference
  latency/resource measurements and preserved failures.
- [Packaging](docs/releasing.md): build the wheel and source ZIP with both skills
  and curated evidence.
- [axe-tree-control](.agents/skills/axe-tree-control/SKILL.md): semantic simulator
  control for the user's goal.
- [axe-grid-control](.agents/skills/axe-grid-control/SKILL.md): screenshot control
  when visual localization is requested or needed.

The skills live in `.agents/skills/` for project discovery and allow automatic
selection. Invoke `$axe-tree-control` or `$axe-grid-control` explicitly if useful.
CLI installation installs the Python package, not global skills.

## Data and license

OpenRouter sends the goal, approved literals, and app state to cloud providers;
grid also sends screenshots. Select that destination within the user's authorized
scope. Default reports contain numeric telemetry and bounded status/identity
metadata, not private goals, text, screenshots, or credentials. `observe` explicitly
saves app content to a chosen path. Avoid shell history or tracing of private
arguments; see [data handling](docs/usage.md#data-and-observations).

Author: **Igor Tarasenko**. Package license: **MIT**; the standalone license
file and packaging metadata are included. Provider code, weights, and hosted
services have separate licenses and terms, described in the provider contracts.
