# One skill source for Claude Code and Codex

The **0.2.0 plugin package** exposes two canonical skills from root `skills/`.
Claude Code and Codex use separate manifests and marketplace catalogs but load
the same files. The Python distribution has its own version in `pyproject.toml`;
plugin versioning does not imply a Python release or new model-quality evidence.

```text
repository or extracted source ZIP/
├── .claude-plugin/{plugin,marketplace}.json
├── .codex-plugin/plugin.json
├── .agents/plugins/marketplace.json
├── CLAUDE.md
└── skills/
    ├── axe-tree-control/{SKILL.md,agents/openai.yaml,references/,evals/}
    └── axe-grid-control/{SKILL.md,agents/openai.yaml,references/,evals/}
```

Both manifests declare `skills: "./skills/"`. Both catalogs point to `./`,
relative to the repository/marketplace root, not the metadata directory.
There are no staged copies, symlink bridges, bundled MCP servers, or hooks.
The old `.agents/skills/` definitions were moved; ignored `.agents/runtime/`
is unrelated local state and is never bundled.

## Prefer tree; require an explicit experimental grid request

| Intent | Skill | Gate |
| --- | --- | --- |
| Taps, scrolling, approved text with useful accessibility semantics | `axe-tree-control` | Explicit simulator, supplied point geometry, authorized goal/provider |
| Explicit experimental visual-control request | `axe-grid-control` | Disclose **0/30 strict grid passes**, establish image readiness and destination permission |
| Missing semantics without a visual-control request | Report the limitation | Do not automatically launch grid |

Every run uses the actual user goal, exact approved literals, and fresh targets.
Normal bounds are 20 steps, 120 requests, and a cooperative 300-second deadline.
Model completion belief is separate from independently verified outcome evidence.
The measured gate comes from [the 2026-10-05 comparison](results.md).

## Claude Code

From any working directory, load an absolute checkout or extracted ZIP root:

```sh
claude --plugin-dir /absolute/path/to/axe-decision-control
```

Inside that session, invoke `/axe-decision-control:axe-tree-control` or
`/axe-decision-control:axe-grid-control`. Plugin skills are namespaced by manifest
name. `CLAUDE.md` supplies guidance when working in this repository; Claude does
not load a plugin-root `CLAUDE.md` as installed project context. Each skill
carries its own instructions and references for installations outside the checkout.

For an explicitly chosen marketplace installation, register the absolute root
with `/plugin marketplace add /absolute/path/to/axe-decision-control`, then use
`/plugin install axe-decision-control@axe-decision-control-marketplace`.
Those commands change client settings; packaging checks do not execute them.

## Codex

The repo catalog is `.agents/plugins/marketplace.json`. Register the checkout
explicitly; a repo-local catalog is not automatically registered in an existing
client configuration. The installed CLI's read-only marketplace listing did not
include this new catalog before registration. The following command changes
client configuration, so run it only when you want to add this source:

```sh
codex plugin marketplace add /absolute/path/to/axe-decision-control
```

Then open the CLI plugin browser with `/plugins`, choose **AXe Decision Control**,
and install/enable it. After starting a new chat, invoke `$axe-tree-control` or
`$axe-grid-control`; the skill's `agents/openai.yaml` carries those starter
prompts. Type `$` and confirm the discovered name in the client's skill picker.
Do not reuse Claude's slash syntax as a Codex invocation.

This package uses the supported `.codex-plugin/plugin.json` compatibility
layout, matching installed Codex plugins and plugin-creator output. Current
OpenAI documentation also describes a newer portable root `plugin.json` format;
this package does not claim to implement that format. No global installation or
project enablement is necessary for the structural checks below.

## Runtime prerequisites and portability

Plugin installation supplies instructions, not `axe-control`, AXe, Xcode,
simulator runtimes, model weights, provider servers, or accounts. Prepare those
separately within the user's scope. With the CLI installed and on PATH, the
skills use `axe-control` from any working directory; they need neither a checkout
environment nor an RTK wrapper. [Package setup](usage.md) describes installation.

Each skill's Markdown links resolve directly to bundled `references/*.md`.
Copying either skill directory into a supported host's skill location preserves
its operating references; it does not install the command. Credentials stay in
documented environment variables or key files. Goals, literals, accessibility
content, and images require permission for the actual provider destination;
loopback is not proof that a tunnel stays local. Captures persist content and
need an explicit request and chosen overwrite-safe destination.

## Export and validate without inference

The exporter selects both metadata trees, only `.agents/plugins` from local
agent state, canonical `skills/`, `CLAUDE.md`, source/tests/tools, docs, benchmark
fixtures, recorded results including media, and the required root `evals/` and
`.github/` offline CI files. Teaching media lives under `docs/media/`;
skill-local eval cases also travel with each skill.
Existing privacy/cache/binary and symlink exclusions still apply. Output must
be a new path outside selected roots; no duplicate staging tree is created.

```sh
uv run --no-sync --offline python -B tools/package_source.py --output /absolute/path/source.zip
uv run --no-sync --offline pytest tests/test_plugin_packaging.py
claude plugin validate .claude-plugin/plugin.json
claude plugin validate .claude-plugin/marketplace.json --strict
```

ZIP tests relocate the exported artifact and resolve marketplace sources,
manifest skill paths, and every local skill Markdown reference. They check
individually copied skills, exclusions, and educational assets. Skill eval JSON
contains manual routing/safety scenarios; passing packaging tests is not a model
evaluation. No paid inference or simulator actions are needed for these checks.
Native Claude validation is schema evidence. It warns that root `CLAUDE.md` is
repository context rather than installed plugin context; `--strict` on the plugin
therefore fails on that expected warning. Marketplace validation is strict.
Actual host discovery and successful
task execution require a separately authorized client session and runtime.

## Primary format references

Format checked 2026-10-12 against installed metadata and official documentation:

- [Claude plugin manifests](https://code.claude.com/docs/en/plugins-reference)
- [Claude marketplaces and namespaced skills](https://code.claude.com/docs/en/plugin-marketplaces)
- [OpenAI packaging, compatibility manifests, and repo marketplaces](https://developers.openai.com/plugins/build/plugins.md)
- [OpenAI skills and Codex dollar invocation](https://developers.openai.com/plugins/build/skills.md)
