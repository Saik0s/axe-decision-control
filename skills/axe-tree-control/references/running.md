# Run tree control from any directory

Prerequisites: Python 3.12+, macOS, selected full Xcode, a booted iOS Simulator
with the intended app open, compatible AXe on PATH, and installed `axe-control`.
Installing the plugin supplies instructions only. If the CLI is absent, report
that prerequisite; do not install software or a provider server without scope.

Check the installed command without model calls or simulator changes:

```sh
axe-control --help
axe-control doctor
```

Select `AXE_UDID` as one real simulator UDID and `AXE_POINTS` as supplied logical
`WIDTHxHEIGHT`, not screenshot pixels. Set `AXE_GOAL` to the actual user goal.
Do not use a fixture goal or reusable element IDs. This example uses an already
authorized OpenRouter/JeV 1.14 destination:

```sh
axe-control run \
  --udid "${AXE_UDID:?Select one explicit simulator}" \
  --points "${AXE_POINTS:?Supply logical WIDTHxHEIGHT}" \
  --goal "${AXE_GOAL:?Supply the actual goal}" \
  --provider openrouter --model typesafe/jev-1.14 --mode tree \
  --max-steps 20 --max-requests 120 --max-seconds 300
```

For entry, add `--text "${AXE_TEXT:?Supply an exact approved literal}"`; repeat
the option for each approved literal. Omit it when no entry is requested. Do not
echo values or retain them in shell history, traces, logs, or reports. Command
arguments can be visible to process inspection; use the package's library in a
private process when that exposure is unacceptable, or stop with that limitation.

Tree, grid, and box default to `typesafe/jev-1.14` with OpenRouter; keep the
explicit `--model` in commands so the selected route is reviewable. For Clef
tree, replace the model with `cloudflare/clef`. For Winnow tree, replace the
provider/model pair with `--provider winnow --model Winnow-12B` and set
`--base-url "${AXE_BASE_URL:?Select the authorized API base and port}"`.
Choose the destination before execution, not as a retry fallback.

The frozen JeV tree comparison used `typesafe/jev-1.13`, the historical
text-only adapter route. Its scores do not measure JeV 1.14.

Exit 0 means a fresh model completion judgment; exit 2 includes blocked, failed,
cancelled, and budget-exhausted runs. Defaults are 0.9 completion belief, 20 steps,
120 requests, and a cooperative 300-second deadline. Do not interpret these as
an outcome guarantee. Three consecutive stale decisions or three actions with no
observable change block the run. Keep failure reasons visible.

`--report` writes sanitized numeric telemetry to a deliberately chosen file;
it is separate from app-content capture. Missing provider cost is unknown, not
zero. Use a persistent capture only when explicitly requested, and choose a path
that may safely be overwritten:

```sh
axe-control observe \
  --udid "${AXE_UDID:?Select one explicit simulator}" \
  --points "${AXE_POINTS:?Supply logical WIDTHxHEIGHT}" \
  --format tree --output "${AXE_CAPTURE_PATH:?Choose a capture destination}"
```

This writes app content. Do not attach private captures to telemetry or public
proof. For a non-default AXe executable, `run` and `observe` accept `--axe`;
`doctor` checks `axe` on PATH.
