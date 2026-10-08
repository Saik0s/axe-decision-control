# Usage

The CLI and library run one user-supplied goal against one explicit iOS Simulator.
Commands below match the current parser. Clean installation and controlled native
execution have current evidence. [Results](results.md) separates the completed
105-episode native comparison from local inference measurements. Grid remains
experimental, with 0/30 strict native passes; examples alone prove neither.

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
to `cloudflare/clef`; direct defaults to `openai/gpt-4.1-mini`. Prefer an explicit
model selection. The supported Jev selector is `typesafe/jev-1.13` for tree only;
moving aliases and direct TypeSafe selectors are not interchangeable with it.

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

Tree control through Clef:

```sh
rtk proxy uv run --no-sync --offline axe-control run \
  --udid "${AXE_UDID:?Select one simulator}" \
  --points "${AXE_POINTS:?Supply logical WIDTHxHEIGHT}" \
  --goal "${AXE_GOAL:?Supply the user goal}" \
  --text "${AXE_TEXT:?Supply an approved literal}" \
  --provider openrouter --model cloudflare/clef --mode tree \
  --max-steps 20 --max-requests 120 --max-seconds 300
```

For Jev tree decisions, replace only the model with `typesafe/jev-1.13`. Both
models use OpenRouter credentials and send task/app content to a cloud provider.

Screenshot grid control through an already image-capable Winnow service:

```sh
rtk proxy uv run --no-sync --offline axe-control run \
  --udid "${AXE_UDID:?Select one simulator}" \
  --points "${AXE_POINTS:?Supply logical WIDTHxHEIGHT}" \
  --goal "${AXE_GOAL:?Supply the user goal}" \
  --text "${AXE_TEXT:?Supply an approved literal}" \
  --provider winnow --model Winnow-12B \
  --base-url "${WINNOW_BASE_URL:-http://127.0.0.1:8091}" --mode grid \
  --max-steps 20 --max-requests 120 --max-seconds 300
```

Clef grid uses `--provider openrouter --model cloudflare/clef --mode grid` with
the normal OpenRouter base. Its gateway image encoding passed a hosted
contrasting-image probe, separately from simulator grounding. Reject Jev for grid
rather than converting screenshots into a text mode.
Grid sees screenshots and geometry, never accessibility selectors or bounds.
It taps a field before typing if focus is needed. Its default grid is 4 columns
by 8 rows, followed by 4 by 4 refinement; those dimensions are library settings,
not CLI flags.

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
default. Clef/Jev decision models are not direct-mode chat models. Direct reads
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
`OpenRouterProvider(model="typesafe/jev-1.13")` from
`axe_control.providers.openrouter`, with the documented credentials. For grid,
set `mode="grid"`, supply `screen`, and use a verified image-capable provider.
The library can set grid dimensions and image-change tolerance through `RunConfig`.
Call `cancellation.set()` from the caller to request a cooperative stop; an
`on_event` callback receives content-free `Event` telemetry.

## Project skills

In an agent that discovers project skills, use
[$axe-tree-control](../.agents/skills/axe-tree-control/SKILL.md) for accessibility
decisions or [$axe-grid-control](../.agents/skills/axe-grid-control/SKILL.md) for
screenshot decisions. Keep the repository layout: both skills link to `docs/`
relative to their skill directories. Copying one skill directory alone does
not carry those references with it. The CLI wheel contains the Python package,
not the skills, fixture, or benchmark modules.

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
[0, 1]. These are uncalibrated model-belief thresholds, not permission, hit
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
for tree/direct, or screenshots for grid. Local Winnow keeps requests at the
configured service; choosing a remote base moves the data boundary. The adapter's
`local` identity flag identifies a loopback service endpoint. A loopback tunnel
can still lead to a remote model host. Establish the destination within the user's
authorized scope before sending app content.

Reports contain counts, timings, beliefs, events, and sanitized model/endpoint
metadata, not goals, text literals, raw app state, images, answer distributions,
or credentials. Missing provider cost is unknown, not zero. Backend allocated
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
