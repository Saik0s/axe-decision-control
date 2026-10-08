---
name: axe-tree-control
description: Control an iOS Simulator for the user's goal through AXe accessibility targets and bounded typed decisions. Prefer this when controls expose useful semantics.
---

# AXe tree control

Read [usage](../../../docs/usage.md) for CLI/library calls and
[provider contracts](../../../docs/provider-contracts.md) for the selected provider.
Resolve these paths from this skill directory. Use the existing package; do not
build another routing layer or replace the user's goal with a fixture task.

- Keep the requested outcome and authorization. Select one explicit simulator
  UDID and its logical point dimensions; never choose `booted` or guess geometry.
- Extract only exact, user-approved text into repeated `--text` options or
  `Task.allowed_texts`. Do not paraphrase, invent, or log input literals.
- Use `--mode tree` with `--provider openrouter --model cloudflare/clef`,
  `--provider openrouter --model typesafe/jev-1.13`, or
  `--provider winnow --model Winnow-12B`. Winnow's configurable default base is
  `http://127.0.0.1:8091`; check the caller-selected service and explicit port.
- Cloud selection sends the goal, literals, and accessibility content off-host.
  Respect existing authorization for that destination; clarify only if unresolved.
  Read credentials from the documented environment or `--api-key-file`, never a
  secret CLI argument, trace, or report.
- Prefer current semantic targets. References belong to one fresh snapshot;
  never hardcode element IDs or coordinates. Truncated candidates, missing
  semantics, provider failures, and blocked runs require a truthful report.
  Switch observation method only within the user's requested scope.
- Run bounded work, normally 20 steps, 120 model requests, 300 seconds. The time
  budget and cancellation are cooperative: in-flight work may finish late;
  cancellation prevents the next action. Do not raise limits to conceal failure.
- Completion threshold 0.9 is an uncalibrated belief setting, not authorization.
  `completed` is a fresh model judgment. Report numeric telemetry and sanitized
  status, and distinguish independent outcome evidence from that judgment.
- Use `observe` only when capture is explicitly requested: it persists app
  content. Consult [measured results](../../../docs/results.md) for this package's
  evidence; verify each new run from its current observations and report.
