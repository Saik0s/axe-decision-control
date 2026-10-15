# Usage

The CLI and library run one user-supplied goal against one explicit iOS Simulator.
Commands below match the current parser. [Results](results.md) separates the completed
105-episode native comparison, frozen on 2026-10-05, from local inference
measurements. Its **0/30 strict grid passes** came from Clef/Winnow, not JeV 1.14.
Grid and box control remain experimental. The JeV 1.14 image/box provider probe
is separate from native task success. Saved synthetic native evidence from
2026-10-15 records passing tree/grid and final guided-box duration demos, alongside
three retained generic-box attempts blocked by the presence gate. These are
prototype observations, not a broad benchmark or general accuracy estimates.

## Install and select the target

Use Python 3.12+, uv, macOS with a selected full Xcode installation and an
installed iOS Simulator runtime, and an AXe executable compatible with that
Xcode version. AXe must be on PATH unless selected with `--axe`.
Run checkout commands from the repository root, wherever it is cloned.
`rtk proxy` is an optional command wrapper; omit that prefix if RTK is absent.

Prepare the checkout environment once from the bundled lock file:

```sh
rtk proxy uv sync --frozen
rtk proxy uv run --no-sync --offline axe-control --help
```

`--no-sync --offline` uses that prepared environment without updating the lock
file or downloading dependencies. If it is missing, complete the preparation
step first. `--offline` applies to uv's dependency resolution; a `run` still
contacts the configured model service and controls the selected simulator.
For a persistent CLI available outside the checkout, instead use:

```sh
rtk proxy uv tool install .
rtk proxy axe-control --help
```

Ensure uv's tool executable directory is on PATH. With that installation,
replace `rtk proxy uv run --no-sync --offline axe-control` in the examples with
`rtk proxy axe-control`. A tool installation is isolated; it does not make the
library importable by an unrelated Python environment. The library example
uses the prepared checkout environment or a separate environment with the
package installed.

Neither route installs AXe, simulator runtimes, model weights, a provider server,
or global skills. The caller must select and boot the simulator and open the
intended app. See [benchmarks](benchmarks.md) for the separate fixture setup.

The only CLI subcommands are `doctor`, `observe`, and `run`. `doctor` checks AXe
and Xcode versions without changing a simulator:

```sh
rtk proxy uv run --no-sync --offline axe-control doctor
```

Every `run` and `observe` requires `--udid` and `--points`. Set `AXE_UDID` to one
real simulator UDID, never `booted`; set `AXE_POINTS` to its logical `WIDTHxHEIGHT`.
Screenshot pixels are a different unit. Supply the dimensions rather than
guessing from a device name or assuming a fixed display scale. `--axe` can select
an executable/path for `run` and `observe`; `doctor` checks `axe` on PATH.

## Provider and credentials

OpenRouter's default base URL is `https://openrouter.ai/api`. Tree/grid default
to `typesafe/jev-1.14`, as does box; direct defaults to `openai/gpt-4.1-mini`.
Prefer an explicit model selection. JeV 1.14 supports text/image decisions and
experimental boxes. The adapter requires its resolved response model to be
`typesafe/jev-1.14-20261014`. This versioned selection does not use a moving
latest alias. Direct TypeSafe selectors `jev-1.14.0` and `jev-preview` belong to
a different API, which this package does not implement; its latest-alias
documentation still names 1.13 as of the 2026-10-15 review.

`typesafe/jev-1.13` remains a historical text-only tree route in this adapter.
That restriction describes this package, not current upstream 1.13 image support.

OpenRouter reads `OPENROUTER_API_KEY_FILE` or `OPENROUTER_API_KEY`. Winnow reads
`WINNOW_API_KEY_FILE` or `WINNOW_API_KEY` when its server requires authentication.
An explicit `--api-key-file` takes precedence over the environment; otherwise
the provider's key-file variable takes precedence over its key variable. There
is no CLI `--api-key` option. Use an existing readable file or securely supplied
environment, never a key literal in a command, report, or shell trace.

Winnow defaults to model `Winnow-12B` and base `http://127.0.0.1:8091`. Use
`--base-url` to select a different caller-managed service. This package does not
launch servers or probe their capabilities automatically. CLI Winnow currently
permits image requests; this is not evidence of a loaded matching projector.
In the library, `WinnowProvider(vision=False)` disables images for a text-only service.
Read [provider contracts](provider-contracts.md) before choosing the image route.

## Run a goal

Set `AXE_GOAL` to the user's actual goal. If entry is needed, set `AXE_TEXT` to
one exact literal the user approved. The examples with `--text` require that
literal; omit the option when no text is needed and repeat it for each additional
approved value. The package selects from this catalog, not generated text.

Tree control through JeV 1.14:

```sh
rtk proxy uv run --no-sync --offline axe-control run \
  --udid "${AXE_UDID:?Select one simulator}" \
  --points "${AXE_POINTS:?Supply logical WIDTHxHEIGHT}" \
  --goal "${AXE_GOAL:?Supply the user goal}" \
  --text "${AXE_TEXT:?Supply an approved literal}" \
  --provider openrouter --model typesafe/jev-1.14 --mode tree \
  --max-steps 20 --max-requests 120 --max-seconds 300
```

For Clef tree decisions, replace only the model with `cloudflare/clef`. Both
models use OpenRouter credentials and send task/app content to a cloud provider.

For explicitly requested experimental screenshot grid control through JeV 1.14:

```sh
rtk proxy uv run --no-sync --offline axe-control run \
  --udid "${AXE_UDID:?Select one simulator}" \
  --points "${AXE_POINTS:?Supply logical WIDTHxHEIGHT}" \
  --goal "${AXE_GOAL:?Supply the user goal}" \
  --text "${AXE_TEXT:?Supply an approved literal}" \
  --provider openrouter --model typesafe/jev-1.14 --mode grid \
  --max-steps 20 --max-requests 120 --max-seconds 300
```

The adapter supplies JeV's image opt-in header and prepares PNG/JPEG inputs before
HTTP. Its conservative minimum side is **280 pixels**, versus upstream's published
256-pixel floor; the maximum remains 1568 pixels. See [image contracts](provider-contracts.md#images)
for the empirical reason and area limits.
Clef grid uses `--provider openrouter --model cloudflare/clef --mode grid` with
the normal OpenRouter base. An already image-capable Winnow service uses
`--provider winnow --model Winnow-12B --base-url "${WINNOW_BASE_URL:-http://127.0.0.1:8091}"`.
The historical `typesafe/jev-1.13` adapter route rejects images/grid; JeV 1.14
supports them. Provider image evidence is separate from simulator grounding.
Grid sees screenshots and geometry, never accessibility selectors or bounds.
It taps a field before typing if focus is needed. Its default grid is 4 columns
by 8 rows, followed by 4 by 4 refinement; those dimensions are library settings,
not CLI flags.

### Experimental box control

For an explicitly requested box run, JeV 1.14 localizes one visible control from
the screenshot and taps its normalized box center in logical simulator points.
Use narrow caller-supplied control descriptions with repeated `--target` options.
The descriptions below belong to the synthetic session workflow; replace them
with the caller's descriptions for another app or goal.

```sh
rtk proxy uv run --no-sync --offline axe-control run \
  --udid "${AXE_UDID:?Select one simulator}" \
  --points "${AXE_POINTS:?Supply logical WIDTHxHEIGHT}" \
  --goal "${AXE_GOAL:?Supply the user goal}" \
  --provider openrouter --model typesafe/jev-1.14 --mode box \
  --target 'New session button' \
  --target 'Session name editable field' \
  --target '50 min duration button' \
  --target 'Quiet mode control' \
  --target 'Start session button' \
  --minimum-present 0.9 --minimum-box-confidence 0.8 \
  --max-steps 20 --max-requests 120 --max-seconds 300
```

Add approved `--text` literals if needed. Box requires decision, vision, and
`capabilities.boxes` support; Clef/Winnow and the historical JeV 1.13 adapter
route do not expose boxes. It receives no accessibility data or benchmark oracle.
Only box mode uses these descriptions: a typed Choice question selects a target
alongside the operation, then Box and Noul questions refer to that explicit
target. The descriptions guide selection; they are not accessibility selectors
or an automatic sequence of clicks. Generic box control without `--target`
remains supported, but the generic next-control prompt has produced presence
uncertainty and blocked attempts. Narrow guidance does not guarantee success.

Noul checks visible target presence; Box requests an enabled control with an
unobstructed center. Presence, box confidence, and screenshot freshness must
pass before tapping. If presence and confidence are both at least 0.5 but either
is below its final gate, the planner makes at most one crop-refinement request.
It pads the candidate by 6% of full-image width/height on each side, clips to
the image, and enlarges the crop 2× before adapter preparation caps each side at
1568 pixels. Returned crop edges map back to full-image coordinates.
The final presence/confidence gates remain 0.9/0.8 by default. A box
alone is insufficient because the primitive returns one even when the target is
absent. The 0.9/0.8 defaults are **uncalibrated demo heuristics**, not calibrated
presence probabilities or hit guarantees. Text entry shares grid's approved
literal and preceding focus-tap rules. See [box contracts](provider-contracts.md#experimental-box-decisions).

### Direct generative control

Direct generative control through Winnow:

```sh
rtk proxy uv run --no-sync --offline axe-control run \
  --udid "${AXE_UDID:?Select one simulator}" \
  --points "${AXE_POINTS:?Supply logical WIDTHxHEIGHT}" \
  --goal "${AXE_GOAL:?Supply the user goal}" \
  --provider winnow --model Winnow-12B \
  --base-url "${WINNOW_BASE_URL:-http://127.0.0.1:8091}" --mode direct \
  --max-steps 20 --max-requests 120 --max-seconds 300
```

Add approved `--text` values if needed. An OpenRouter direct run needs a
generative model that actually supports function calls, such as the configured
default. Clef/JeV decision models are not direct-mode chat models. Direct reads
accessibility state and requires exactly one actual `simulator_action` function
call per response. It exposes TAP, TYPE_TEXT, SCROLL_UP, SCROLL_DOWN, WAIT, and
DONE, with current semantic references and approved literals. A JSON message is
not a substitute for `tool_calls`; the model has no host shell or filesystem tool.

## Library example

Import from the concrete modules; the package root does not re-export `run`.
This example runs tree control against a text-only Winnow service. The environment
inputs must come from the authorized caller. This is example source, not a record
of an executed run.

```python
import os
import threading

from axe_control.models import RunConfig, ScreenSize, Task
from axe_control.native import AXeTransport
from axe_control.providers.winnow import WinnowProvider
from axe_control.runner import run

width, height = os.environ["AXE_POINTS"].lower().split("x")
screen = ScreenSize(width=float(width), height=float(height))
task = Task(
    goal=os.environ["AXE_GOAL"],
    allowed_texts=[os.environ["AXE_TEXT"]] if "AXE_TEXT" in os.environ else [],
)
transport = AXeTransport(os.environ["AXE_UDID"], screen=screen)
cancellation = threading.Event()
with WinnowProvider(
    model="Winnow-12B",
    base_url=os.environ.get("WINNOW_BASE_URL", "http://127.0.0.1:8091"),
    vision=False,
) as provider:
    report = run(
        provider,
        transport,
        task,
        RunConfig(mode="tree", screen=screen, max_steps=20,
                  max_requests=120, max_seconds=300),
        cancellation=cancellation,
    )
print(report.model_dump_json(indent=2))
```

For hosted tree control, use
`OpenRouterProvider(model="cloudflare/clef")` or
`OpenRouterProvider(model="typesafe/jev-1.14")` from
`axe_control.providers.openrouter`, with the documented credentials. For grid,
set `mode="grid"`, supply `screen`, and use a verified image-capable provider.
For experimental box control, use `mode="box"`, supplied `screen`, and JeV 1.14;
`RunConfig` exposes `minimum_present` and `minimum_box_confidence`.
`Task.target_descriptions` is an optional list of caller-supplied control
descriptions, equivalent to repeated CLI `--target` options; only box uses it.
The library can set grid dimensions and image-change tolerance through `RunConfig`.
Call `cancellation.set()` from the caller to request a cooperative stop; an
`on_event` callback receives content-free `Event` telemetry.

## Agent plugins and skills

Install the [Claude Code or Codex plugin](plugins.md). Both load one canonical
[`skills/`](../skills/) bundle. Each skill carries its own `references/`, so
installed workflows work outside this checkout. In Codex invoke
[$axe-tree-control](../skills/axe-tree-control/SKILL.md), or explicitly request
experimental [$axe-grid-control](../skills/axe-grid-control/SKILL.md). Claude
Code uses the namespaced slash commands shown in the installation guide.
The CLI wheel installs the Python package; plugin skills, fixture and evaluation
modules travel with the source checkout or ZIP, not the wheel.

## Limits and results

Defaults: 20 steps, 120 model requests, 300 seconds. Allowed configuration ranges
are 1–100 steps, 1–1000 requests, and 1–3600 seconds. Steps are loop iterations,
including stale decisions and completion checks, not a count of native commands.
Request accounting includes provider-recorded decision/generative HTTP attempts,
including failed responses and fresh completion requests. A grid tap can require
several requests; a text action can issue several native commands. The direct
baseline uses this same actual request budget, not an estimated token/tool cost.

The deadline is checked between operations. An in-flight HTTP/native call may
finish beyond the budget, and Ctrl-C prevents the next action rather than
instantly cancelling that call. Provider HTTP timeout defaults to 90 seconds;
native command timeout defaults to 30 seconds. Neither is a hard whole-run limit.

`--minimum-done` defaults to 0.9 and `--minimum-inside` to 0.5. They must be in
[0, 1], as must box's `--minimum-present` (0.9) and
`--minimum-box-confidence` (0.8). These are uncalibrated thresholds, not permission, hit
guarantees, or independent evidence. Three consecutive stale decisions or three
actions with no observable change block the run.

The CLI prints progress plus a sanitized final summary. `--quiet` prints only
the final status. `--report` writes content-free JSON telemetry to the chosen
file. Exit 0 means `completed`; blocked, failed, cancelled, and budget-exhausted
runs exit 2. **`completed` means the model confirmed the goal on a fresh
observation.** Confirm real task outcomes with evidence appropriate to the goal;
benchmark success is determined separately by the independent oracle.

## Data and observations

OpenRouter receives the goal, approved literal catalog, and accessibility content
for tree/direct, or screenshots for grid/box. Box target descriptions are also
sent to the provider. Local Winnow keeps requests at the
configured service; choosing a remote base moves the data boundary. The adapter's
`local` identity flag identifies a loopback service endpoint. A loopback tunnel
can still lead to a remote model host. Establish the destination within the user's
authorized scope before sending app content.

Reports contain counts, timings, beliefs, events, and sanitized model/endpoint
metadata, not goals, text literals, target descriptions, raw app state, images,
answer distributions, or credentials. Box telemetry includes numerical normalized bounds, presence
belief, box confidence, and tap points; it saves no screenshot by default.
Missing provider cost is unknown, not zero. Backend allocated
bytes are a device/backend observation, not a per-request peak. Keep private CLI
arguments out of shell history and command traces; use the library when argument
visibility would expose private input. Never dump HTTP bodies or environment keys.

`observe` is an explicit capture operation: tree saves normalized app content as
JSON and screenshot saves image bytes. It creates the requested output path and
overwrites an existing file, so choose the destination deliberately. After capture
is requested, select `AXE_CAPTURE_PATH` and run either command:

```sh
rtk proxy uv run --no-sync --offline axe-control observe \
  --udid "${AXE_UDID:?Select one simulator}" \
  --points "${AXE_POINTS:?Supply logical WIDTHxHEIGHT}" \
  --format tree --output "${AXE_CAPTURE_PATH:?Choose a capture destination}"

rtk proxy uv run --no-sync --offline axe-control observe \
  --udid "${AXE_UDID:?Select one simulator}" \
  --points "${AXE_POINTS:?Supply logical WIDTHxHEIGHT}" \
  --format screenshot --output "${AXE_CAPTURE_PATH:?Choose a capture destination}"
```

Capture is separate from content-free telemetry. Do not attach private captures
to reports or public benchmark artifacts.

The separate [JeV demo recorder](../tools/record_jev_demos.py) is an explicit
synthetic capture workflow for tree/grid/box demos. Its repeated `--target`
options supply workflow guidance to box only. Even with the same goal and initial
state, that extra guidance means the modes are **not a controlled benchmark**.
It makes paid model calls and saves screenshots, recordings, and questions/responses, without
embedded image bytes in the question records. It is not ordinary `run` telemetry.

### Recorded prototype observations, 2026-10-15

Saved episodes independently pass the same synthetic goal: start “Review PR” for
50 minutes with Quiet mode on, from the same initial state. Each has
`Episode.issues() == []`. These are individual prototype observations, not a
broad benchmark; the box run has additional caller workflow guidance.

| Route | Provider calls | Controller time | Saved episode |
| --- | --- | --- | --- |
| Tree | 8 | 12.216 s | [Independent pass](../results/jev-1.14-2026-10-15/tree/episode.json) |
| Grid | 22 | 26.452 s | [Independent pass](../results/jev-1.14-2026-10-15/grid/episode.json) |
| Box, final image fix | 18 | 24.056 s | [Independent pass](../results/jev-1.14-2026-10-15/box-image-fix/box/episode.json) |

The final box run retained the 0.9 presence and 0.8 confidence gates.
Three earlier generic-box attempts remain
retained: [initial](../results/jev-1.14-2026-10-15/box/run-report.json),
[visibility-question revision](../results/jev-1.14-2026-10-15/box-atomic-visibility/box/run-report.json),
and [crop refinement](../results/jev-1.14-2026-10-15/box-crop-refinement/box/run-report.json).
Presence uncertainty around 0.81–0.89 correctly blocked them at the unchanged
0.9 gate. Retaining those attempts prevents the final passing run from hiding
earlier failures. The historical [results overview](results.md) remains frozen.
