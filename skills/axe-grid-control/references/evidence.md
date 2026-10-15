# Historical grid results do not measure JeV 1.14

Historical snapshot: frozen corrected synthetic native comparison, 2026-10-05,
with **105 matched episodes** across all included routes. Full source record:
repository `docs/results.md` and `results/native-comparison/summary.json`.
This bundled summary needs no checkout; grid accounts for 30 of those episodes.

That frozen Clef/Winnow grid comparison had **0/30 strict passes**: Clef 0/15 and
Winnow 0/15. These are not current JeV 1.14 grid or Box statistics. Winnow
independently reached 2/15 outcomes but did not pass controller completion. Clef's 15 attempts
stopped below the tap-belief threshold. Winnow retained six low completion
judgments, eight repeated-no-change stops, and one time-budget exhaustion.
Thresholds were not lowered to manufacture passing results.

The same recorded comparison included Clef tree 12/15, JeV 1.13 tree 12/15, and
Winnow tree 3/15 strict passes. Samples are small and synthetic; they establish
neither reliability for another app nor a causal advantage of observation mode.

Separate capability evidence, 2026-10-15: parent source verification of the
[OpenRouter listing](https://openrouter.ai/typesafe/jev-1.14) and
[endpoint metadata](https://openrouter.ai/api/v1/models/typesafe/jev-1.14/endpoints)
identified text+image decisions and resolved `typesafe/jev-1.14-20261014`.
The parent reported HTTP 200 and an actual box from `/alpha/decisions` with
`text` + `image_url` state parts and Noul + Box questions. This is wire-support
evidence, not a fresh simulator demo, successful goal, calibration, or measured
JeV 1.14 grid/Box control accuracy. Both visual routes remain experimental.

The parent-owned repository tool `tools/record_jev_demos.py` makes paid model
calls and mutates the selected simulator. Its explicit synthetic capture includes
screenshots and question/response records without embedded image bytes. It is
not bundled with this skill, required for installed use, or evidence of success
by its existence. Recording requires authorization for those calls, mutations,
and captures; ordinary telemetry remains sanitized. No fresh demo success is
claimed here.

A strict pass required controller completion, independently checked fixture
state, visible final facts, and valid proof/exit accounting. Grid execution,
native taps, model confidence, and fresh `completed` judgments are individually
weaker evidence. Require an explicit experimental visual-control request, retain
the current bounds, and report failure honestly. For a new goal, distinguish
visual outcome evidence from model belief without introducing an accessibility
oracle into grid planning or verification.
