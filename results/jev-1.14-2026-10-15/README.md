# Jev 1.14 native demonstrations · 15 October 2026

[Watch the visual lesson](../../docs/jev-1.14.html). Actual OpenRouter requests,
native video, screenshots, and independent fixture checks. These are demonstrations,
not a controlled benchmark or general app accuracy measurement.

All runs use the `duration` scenario, seed 12, logical geometry 402 × 874, and the
synthetic FocusBench app. Goal: **Review PR**, **50 minutes**, **Quiet mode on**,
session running. Initial state: home screen, empty name, 10 minutes, Quiet mode off.
No accessibility or oracle data enters grid/box decisions. Box's final version
receives an additional caller-defined target catalog; that difference matters.

| Recording | Independent result | Requests | Controller seconds | Reported cost |
| --- | --- | ---: | ---: | ---: |
| [Tree](tree/episode.json) | Pass | 8 | 12.216 | $0.000348 |
| [Grid](grid/episode.json) | Pass | 22 | 26.452 | $0.004825 |
| [Box, final](box-image-fix/box/episode.json) | Pass | 18 | 24.056 | $0.002784 |

Model requested: `typesafe/jev-1.14`. Every successful call resolved to
`typesafe/jev-1.14-20261014`. Costs are provider-reported usage, not total host cost.
Clips and controller timings have separate clocks. The strict result joins actual
controller completion with persisted fixture state, visible final facts, and saved
proof. [Machine-readable evidence](evidence.json) includes every attempt and hashes
of the original episode files.

## Failed attempts stay in the record

1. [Initial Box](box/episode.json): presence below the 0.90 gate; no native taps.
2. [Atomic visibility](box-atomic-visibility/box/episode.json): one native tap,
   then the name field remained below presence/confidence gates.
3. [Crop refinement](box-crop-refinement/box/episode.json): one native tap,
   then a closer crop still failed the presence gate.
4. [Caller-described targets](box-described-targets/box/episode.json): five
   controller actions, then OpenRouter rejected a 278 × 394 refinement image with
   HTTP 400. The documented dimensions allow that image; live probes rejected
   width 278 but accepted width 280 and above for the same content.
5. [Image preparation fix](box-image-fix/box/episode.json): full independent pass.
   Refinement enlarges the crop before sending it, and the adapter uses a
   conservative minimum side of 280 pixels. Gates remain presence 0.90 and box
   confidence 0.80, with one refinement at most per planned tap.

The final Box run supplies these descriptions: New session button, Session name
editable field, 50 min duration option, Quiet mode control, and Start session
button. Jev selects the next target against the screenshot and goal; code does
not prescribe an action sequence. Descriptions are workflow hints, not measured
accessibility labels, selectors, or control bounds. The generic target search's
failures remain visible rather than being credited as successes.

## Reproduce on an explicitly selected simulator

Requires macOS, Xcode, AXe, uv, OpenRouter credentials and a booted simulator.
The commands below make paid calls and intentionally capture synthetic app
screens and typed questions. They never persist credentials or embedded image
bytes in the question log. Choose a fresh output path; collisions are refused.

```sh
uv sync --frozen
uv run python fixtures/FocusBench/build.py --output benchmark-runs/fixture-build
uv run python -m tools.record_jev_demos \
  --udid "$AXE_UDID" --points "$AXE_POINTS" \
  --app benchmark-runs/fixture-build/FocusBench.app \
  --scenario duration --modes tree grid box \
  --target 'New session button that opens the session creation form' \
  --target 'Session name editable text field' \
  --target '50 min duration option' \
  --target 'Quiet mode toggle or checkbox' \
  --target 'Start session button that starts the configured session' \
  --output benchmark-runs/jev-1.14-reproduction
```

Each folder contains `original.mp4`, `episode.json`, `run-report.json`,
`questions.jsonl`, `final-tree.json`, and `final.png`. Visual runs additionally
save the screenshot used at each step; Box runs save an illustration drawn from
the actual returned full-screen bounds. `questions.jsonl` records the real typed
questions and validated replies; it does not claim to capture model reasoning.
Refinement replies contain crop-relative edges; controller events contain the
mapped full-screen edges and logical tap point.

The [historical comparison](../native-comparison/report.md) remains unchanged:
105 episodes, 46 strict passes, 59 strict failures; Clef/Winnow grid 0/30. Do not
combine this development sequence with that fixed benchmark denominator.
