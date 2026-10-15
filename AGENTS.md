# Repository contract

This is an educational repository. Lead with visual explanations and actual
recordings; link technical detail on demand. `docs/index.html` is the browser
learning path, `README.md` the GitHub entry point. Keep dates and evidence limits
beside claims. Never present replay, test, manifest, or case-file validation as a
fresh provider run or measured agent skill quality.

## Ownership and layout

- `src/axe_control/`: provider-independent contracts and bounded AXe execution.
  Provider modules own wire formats; planners cannot inspect benchmark oracles.
- `skills/`: the single shared plugin skill source. Each skill bundles its own
  one-level references; installed skills must not depend on checkout-relative docs.
- `.claude-plugin/` and `.codex-plugin/`: host-specific manifests. Keep both pointed
  at the same skill source, not duplicate copies.
- `evals/`: declared evaluation cases and offline evidence grading.
  `benchmarks/`: native/inference measurements. `tests/`: regression checks.
- `results/`: immutable, dated synthetic evidence. Never rewrite old episodes to
  match current code or hide failed attempts. Write regrades to ignored artifacts.
- `docs/media/`: teaching diagrams and reproducible previews. Run
  `uv run python -m tools.build_learning_media --previews` to rebuild replay data
  and GIFs; FFmpeg and FFprobe are required for this optional media operation.

Grid planners receive only screenshots and geometry, never accessibility labels,
selectors, control bounds or fixture state. Independent evaluation happens after
control. Completion belief is uncalibrated; `completed` is not an oracle pass.

Box planners also receive no accessibility or oracle data. An explicitly supplied
target-description catalog is workflow guidance, not observed semantics; disclose
it beside any comparison. Jev 1.14 images/boxes are experimental. Preserve raw
failed attempts and show presence/confidence gates separately from independent
outcome checks. `tools/record_jev_demos.py` intentionally captures synthetic app
screens and typed requests; normal run telemetry remains content-free.

## Local checks

Use Python 3.12+ and uv. Prefix shell commands with `rtk proxy` where available;
public documentation must work without RTK. Run `uv run pytest -q`,
`uv run ruff check .`, and `uv run mypy` for source/packaging changes. Verify a
clean wheel/source installation when packaging changes. For guide changes, check
real video playback, event navigation, grid interaction, desktop/mobile layout,
local links and browser errors. No paid inference is part of offline checks.

Keep strict types, finite probabilities, and validated answer IDs. Preserve
module boundaries and existing user work. Default telemetry must not persist
credentials, private goals or raw app content. Synthetic benchmark evidence is
explicitly captured; other captures require user scope. Keep runtime work under
ignored `artifacts/`, `benchmark-runs/`, and `dist/` paths. Commit, push, install
globally, or publish only when requested.
