# Run experimental grid control from any directory

Prerequisites: an explicit experimental visual-control request; Python 3.12+,
macOS, selected full Xcode, a booted iOS Simulator with the intended app open,
compatible AXe on PATH, installed `axe-control`, and an image-ready provider.
The plugin installs none of these executables or services. Report missing
prerequisites rather than provisioning outside the authorized scope.

Read-only toolchain checks make no model calls or simulator changes:

```sh
axe-control --help
axe-control doctor
```

Select one real `AXE_UDID`, supplied logical `AXE_POINTS` in `WIDTHxHEIGHT`, and
the actual `AXE_GOAL`. Screenshot pixels are not logical points; never assume
3x scale or import fixture coordinates. With an already authorized OpenRouter
JeV 1.14 image route:

```sh
axe-control run \
  --udid "${AXE_UDID:?Select one explicit simulator}" \
  --points "${AXE_POINTS:?Supply logical WIDTHxHEIGHT}" \
  --goal "${AXE_GOAL:?Supply the actual goal}" \
  --provider openrouter --model typesafe/jev-1.14 \
  --base-url https://openrouter.ai/api \
  --mode grid --max-steps 20 --max-requests 120 --max-seconds 300
```

For an authorized OpenRouter/Clef image route, replace provider/model/base with
`--provider openrouter --model cloudflare/clef --base-url https://openrouter.ai/api`.
For an image-ready Winnow service, use `--provider winnow --model Winnow-12B`
and `--base-url "${AXE_BASE_URL:?Select the authorized API base and port}"`.
OpenRouter tree/grid/box default to `typesafe/jev-1.14`; keep `--model` explicit.
The historical 1.13 adapter route remains text-only. Choose the destination
before execution; do not silently switch models or services on failure.

For an explicitly requested experimental Box localization run, replace
`--mode grid` above with `--mode box --minimum-present 0.9 --minimum-box-confidence 0.8`.
Use JeV 1.14 with both `capabilities.boxes` and `vision`. The controller pairs
a Noul presence judgment with a normalized Box, checks presence, confidence,
and screenshot freshness before tapping its center in logical points. Box
shares grid's approved-literal focus gate and uses no accessibility/oracle input.
The 0.9/0.8 gates are uncalibrated demo heuristics, not recommended safety or
accuracy thresholds. Do not lower them to force a tap; a box alone is not proof
that the target exists.

For text entry, add `--text "${AXE_TEXT:?Supply an exact approved literal}"`;
repeat for additional approved values and omit when no entry is needed. A fresh
focus tap must be tied to that literal. Never generate replacement text or log
goals/literals. Keep them out of shell history and traces. Arguments may be
visible to process inspection; use the library in a private process if necessary,
or report that privacy limitation before execution.

Default inside/completion beliefs are 0.5/0.9, not calibrated hit probabilities.
Do not lower thresholds to force actions. Bounds are 20 steps, 120 requests,
and a cooperative 300-second deadline; in-flight work can finish late.
Three consecutive stale decisions or three unchanged actions block the run.
Exit 0 means model completion; exit 2 includes blocked, failed, cancelled, and
budget-exhausted work. Neither an executed tap nor exit 0 proves the goal.

`--report` persists sanitized numeric telemetry at a chosen path; missing cost
remains unknown. Box reports include numerical normalized bounds, presence belief,
confidence, and tap points; they save no screenshot by default.
A screenshot capture persists app content, overwrites its
destination, and is allowed only when requested:

```sh
axe-control observe \
  --udid "${AXE_UDID:?Select one explicit simulator}" \
  --points "${AXE_POINTS:?Supply logical WIDTHxHEIGHT}" \
  --format screenshot --output "${AXE_CAPTURE_PATH:?Choose a capture destination}"
```

Keep outcome verification visual. Do not obtain accessibility labels, selectors,
or bounds for the grid planner. Private captures do not belong in telemetry or
public proof. `run` and `observe` accept `--axe` for a non-default executable;
`doctor` checks `axe` on PATH.
