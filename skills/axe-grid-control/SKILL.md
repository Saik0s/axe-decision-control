---
name: axe-grid-control
description: Use for explicitly requested experimental iOS Simulator control through AXe screenshot grids, including the JeV 1.14 image route. Prefer tree for semantic targets.
---

# AXe grid control

**Route gate: grid remains experimental. The frozen 2026-10-05 Clef/Winnow grid
comparison had 0/30 strict passes; it does not measure JeV 1.14.** Prefer tree
when useful semantics exist. Explain this limitation
before running grid. Require an explicit experimental visual-control request;
missing accessibility semantics alone does not authorize switching routes.

1. Confirm the actual goal, authorized actions, one explicit simulator UDID, and
   supplied logical `WIDTHxHEIGHT` point geometry. Never use `booted`, guess
   dimensions, or assume a fixed screenshot scale. Extract exact approved text
   into repeated `--text` options; omit them when no entry is needed. Proceed
   when the target, geometry, literals, and route request are known.
2. Read [running grid control](references/running.md) and
   [provider boundaries](references/providers.md). Use installed `axe-control`.
   Verify image readiness at the explicitly selected model/service; a capability
   flag or health response is insufficient. The bundled OpenRouter JeV 1.14
   adapter supports images; historical JeV 1.13 adapter behavior is text-only.
   Sending goals, literals, and screenshots off-host requires destination
   authorization; reuse existing permission, and clarify only unresolved scope.
   Proceed when the toolchain, image route, and data boundary are established.
3. Run `--mode grid` with pixels, grid geometry, goal, approved literals, and
   action history only. Do not use accessibility labels, selectors, bounds, or
   benchmark oracle state to choose or verify grid actions. The planner uses
   full screenshot plus crop, coarse then fine cells, and actual pixel-to-point
   geometry. Text entry requires a fresh focus tap tied to its approved literal.
   Stop on provider failure, blocking, stale observations, or exhausted budget.
4. Normally bound work to 20 steps, 120 requests, and 300 seconds. Cancellation
   prevents the next action; in-flight work can finish late. Inside/completion
   thresholds 0.5/0.9 are uncalibrated beliefs, not permission or hit guarantees.
   Do not lower thresholds or raise budgets to manufacture success. Report
   sanitized status, numeric telemetry, model, and observed outcome. A fresh
   model `completed` judgment is distinct from independently verified facts;
   [recorded evidence](references/evidence.md) explains that distinction. Keep
   verification visual without feeding an accessibility oracle into the planner.
   Use `observe` only for a requested persistent capture at a chosen destination.
   Finish with outcome evidence or an explicit failure/verification limit.
