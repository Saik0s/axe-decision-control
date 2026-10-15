# Export source, plugins, and teaching material

The wheel installs the `axe-control` CLI and typed `axe_control` library. The
source ZIP additionally includes Claude Code/Codex metadata, canonical `skills/`,
bundled references and evaluation cases, the visual guide and media, benchmarks,
fixture source and dated synthetic results. Neither installs AXe, Xcode, model
weights, credentials or provider services.

## Build from the checkout

```sh
uv sync --frozen
uv build --out-dir dist
uv run --no-sync --offline python -m tools.package_source \
  --output dist/axe-decision-control-source.zip
```

Choose a new output filename if that ZIP already exists. The exporter refuses
collisions, selected-root destinations and symlink inputs. It uses only Python's
standard library and prints the SHA-256 plus sorted members. Review the actual
inventory before sharing: source selection cannot detect every secret.

## What travels with the source ZIP

```text
.claude-plugin/ + .codex-plugin/ + .agents/plugins/   host metadata
skills/                                             one canonical bundle
src/ + pyproject.toml + uv.lock                     Python controller
evals/ + benchmarks/ + fixtures/ + tests/           reproduction and checks
docs/ + results/                                    visual teaching and evidence
```

Caches, environments, ignored runtime task packets, raw local benchmark work,
credentials and model weights stay out. The old `.agents/skills/` source is
retired. Skills do not rely on checkout-relative documentation or symlink bridges.
See [plugin installation and artifact checks](plugins.md).

## Verify the actual artifact

Extract the ZIP into a fresh directory. Resolve both host catalogs/manifests,
read each installed skill and follow its bundled references. Run offline evals
from that extracted checkout. Build/install a wheel into an isolated environment,
check CLI help and library imports, and confirm `py.typed` is installed.

The wheel contains runtime Python only. Source evals and teaching media are not
installed by `uv tool install .`; that command also does not register plugins.
Do not modify a user's global plugin settings as a packaging check.

## Keep releases and measurements separate

Recorded `results/` are immutable historical inputs. A packaging or grader repair
does not rerun the controller; regrade into ignored `artifacts/` and retain the
original measurement date and implementation fingerprint. Passing offline checks
or decoding a video does not establish fresh model quality, simulator execution,
calibrated beliefs or automatic skill routing. Review [evaluation boundaries](evaluations.md)
before making release claims. Publishing requires an explicit user request.
