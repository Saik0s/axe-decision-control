---
name: axe-tree-control
description: Use for iOS Simulator goals through AXe accessibility targets, including taps, approved text entry, and scrolling. Prefer tree control when useful semantics exist.
---

# AXe tree control

1. Confirm the user's actual goal and authorized actions. Select one explicit
   simulator UDID and supplied logical `WIDTHxHEIGHT` point dimensions; never use
   `booted`, infer geometry from a device name, or reuse benchmark coordinates.
   Keep exact approved text in repeated `--text` options; omit them if no entry is
   needed. Do not invent, paraphrase, or log literals. Proceed when the target,
   geometry, goal, and text catalog are known.
2. Read [running tree control](references/running.md) for portable commands and
   [provider boundaries](references/providers.md) before choosing a destination.
   Use the installed `axe-control`; plugin installation does not install it or
   AXe. Respect existing authorization for sending goals, literals, and app
   content to the selected host. Clarify only unresolved permission. Proceed when
   the toolchain and explicitly selected provider/model/base are ready.
3. Run `--mode tree` using fresh accessibility targets. Snapshot references
   expire; do not hardcode element IDs or coordinates. Normally use 20 steps,
   120 model requests, and 300 seconds. Deadlines and cancellation are
   cooperative; in-flight work may finish late. Stop on blocked, failed, stale,
   or budget-exhausted work and report the reason. Do not inflate limits to hide
   failure. Missing semantics does not authorize experimental grid control:
   [recorded evidence](references/evidence.md) includes **0/30 strict grid passes
   for Clef/Winnow in the frozen 2026-10-05 comparison**, not JeV 1.14 results.
   Switch only for an explicit visual-control request within the authorized scope.
4. Report sanitized status, numeric telemetry, selected model, and the observed
   outcome. A `completed` status is a fresh model judgment at an uncalibrated
   threshold of 0.9; it is neither permission nor independent success proof.
   Distinguish independently verified facts from completion belief and unchecked
   facts. Use `observe` only for an explicitly requested persistent capture at a
   chosen destination. Finish when the outcome is evidenced or the precise
   failure/remaining verification is reported.
