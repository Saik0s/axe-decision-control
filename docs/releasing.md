# Prepare a shareable package

The wheel installs the `axe-control` CLI and typed `axe_control` library. The
source ZIP also includes both project skills, benchmark code, fixture source,
documentation and curated synthetic results. Neither artifact includes AXe,
Xcode, simulator runtimes, credentials, model weights or a Winnow server.

Finish the benchmark run and its evidence review before labeling an archive a
release. Preserve failed episodes and incomplete runs with their actual status.
Update the result links and status in README and docs before building.

From the checkout root, with uv installed:

```sh
rtk proxy uv sync --frozen
rtk proxy uv build --out-dir dist
rtk proxy uv run --no-sync --offline python -m tools.package_source \
  --output dist/axe-decision-control-source.zip
```

Omit `rtk proxy` if RTK is absent. The ZIP command uses only the standard library
and prints its SHA-256 and sorted member list. Choose a new filename on subsequent
builds: existing outputs are refused. `uv build` creates the `dist` parent first.

The ZIP uses an explicit source selection, including only the two named skill
directories within `.agents`. It omits runtime task packets, local benchmark
work directories, virtual environments, caches, symlinks, credentials and model
weights. Review the actual archive inventory and curated evidence before sharing;
file selection does not detect secrets accidentally added to a selected source.

Extract the source ZIP into a new directory and install from it with
`uv tool install .`, or prepare the checkout with `uv sync --frozen`. The source
ZIP retains `.agents/skills/axe-tree-control` and `.agents/skills/axe-grid-control`
for project discovery. A wheel installation does not register global skills.

Validate a wheel in a separate Python environment outside the checkout. Confirm
CLI help, library imports, the `py.typed` marker and that the installed source
matches the code measured by the final comparison. Keep native simulator and
provider validation distinct from an import or installation check.
