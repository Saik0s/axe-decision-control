---
name: axe-grid-control
description: Control an iOS Simulator for the user's goal through AXe screenshot grids when visual localization is requested or accessibility semantics are insufficient.
---

# AXe grid control

Read [usage](../../../docs/usage.md) for CLI/library calls and
[provider contracts](../../../docs/provider-contracts.md) for image readiness.
Resolve these paths from this skill directory. Use the existing package; preserve
the user's goal rather than substituting a fixture workflow.

Grid remains experimental: the recorded comparison had 0/30 strict passes.
Native actions and a model's completion belief do not prove the requested outcome.

- Select one explicit simulator UDID and its logical point dimensions. Never
  use `booted`, guess dimensions, or assume screenshots are universally 3x points.
- Keep localization screenshot-only: pixels, grid geometry, goal, approved
  literals, and action history. Do not read accessibility labels, selectors,
  control bounds, or a benchmark oracle to choose or verify grid actions.
- Extract exact, user-approved text into repeated `--text` options or
  `Task.allowed_texts`. Grid text entry requires a fresh focus tap associated
  with that literal. Do not generate additional literals or log their values.
- Use `--mode grid` with OpenRouter `cloudflare/clef` or Winnow `Winnow-12B`.
  Reject Jev images explicitly. Clef's gateway image encoding passed a hosted
  contrasting-image probe; Winnow needs a running image-capable service with its matching
  projector. Adapter flags, files, and a health response do not prove vision.
  Winnow's configurable default base is `http://127.0.0.1:8091`.
- Cloud selection sends the goal, literals, and screenshots off-host. Respect
  existing destination authorization; clarify only if unresolved. Use documented
  credential environment variables or `--api-key-file`, never a secret CLI
  argument, trace, or report. Do not silently switch to another provider.
- Let the planner locate coarse then fine grid cells and scale their centers
  with the actual screenshot size and supplied point dimensions. Use the full
  screenshot plus the selected crop; freshness and verification stay visual.
- Normally bound the run to 20 steps, 120 model requests, 300 seconds. In-flight
  work can finish over budget; cancellation stops the next action, not instantly.
  Default inside/completion thresholds 0.5/0.9 are uncalibrated beliefs, never
  permission or a hit guarantee. Do not lower them to force apparent success.
- Report numeric telemetry and sanitized status. `completed` is a fresh model
  judgment, not an independent oracle result. `observe` explicitly persists app
  content and needs a requested capture destination. Consult
  [measured results](../../../docs/results.md) for this package's evidence;
  verify each new run without introducing an accessibility oracle into the planner.
