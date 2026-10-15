# Select an image-ready provider and data boundary

| Provider/model | API base | Grid readiness |
| --- | --- | --- |
| OpenRouter `typesafe/jev-1.14` | `https://openrouter.ai/api` | Text+image typed decisions; experimental grid and Box support |
| OpenRouter `cloudflare/clef` | `https://openrouter.ai/api` | Bundled image encoding passed a recorded contrasting-image probe |
| Winnow `Winnow-12B` | `http://127.0.0.1:8091` by default | Needs a running image-capable service and matching projector |
| OpenRouter `typesafe/jev-1.13` | `https://openrouter.ai/api` | Historical adapter route remains text-only; no grid/Box through this adapter |

These are adapter contracts and historical probe evidence, not availability or
general visual-grounding proof. Verify readiness for the selected service/model
before grid execution. A vision flag, model/projector files, open port, or health
response alone is insufficient. Do not launch servers, download weights, run
paid probes, or switch providers without authorization for that action.

## JeV 1.14 route and image contract

Source snapshot, 2026-10-15: the [OpenRouter listing](https://openrouter.ai/typesafe/jev-1.14)
advertises text+image input and decisions output. Parent verification of
[endpoint metadata](https://openrouter.ai/api/v1/models/typesafe/jev-1.14/endpoints)
resolved `typesafe/jev-1.14-20261014`; the adapter validates that exact response
identity. Use `--model typesafe/jev-1.14`. It posts text + `image_url` state parts
to `/alpha/decisions` and adds `TypeSafe-Danger-Zone-Images: true` for images/Box.

[TypeSafe images](https://docs.typesafe.ai/images) requires that opt-in header,
still PNG/JPEG, each side 256–1568 pixels, and area 78,400–2,458,624 pixels,
inclusive. The adapter prepares screenshots and grid crops before HTTP with
aspect-preserving resize, including bounded upscales for small crops. It rejects
malformed images and impossible aspect ratios locally. It strips metadata and
validates dimensions before sending. Local adapter caps: at most four images,
4 MiB decoded per image and 8 MiB total, with 6 MiB encoded per-image validation.

Direct TypeSafe uses `jev-1.14.0`/`jev-preview` for Box, distinct from
OpenRouter's pinned route.
Its general alias documentation still names 1.13 in the supplied source snapshot;
do not substitute those aliases into this CLI. There is no direct TypeSafe
provider here. The historical adapter's text-only 1.13 restriction does not
establish an upstream image limitation.
TypeSafe labels images/Box experimental, “dreamer-ready”; availability and
response shape do not establish reliable control.

## Brief Box option

[Box](https://docs.typesafe.ai/primitives/box) returns one rectangle per question:
finite normalized edges in `[0,1]`, `left < right`, `top < bottom`, and finite
confidence in `[0,1]`. An absent target still returns a box. Pair it with Noul
presence and reject insufficient presence/confidence before acting. Box mode
requires typed decisions, `capabilities.boxes`, and `vision`; it maps the center
to supplied logical points and checks screenshot freshness. It shares grid's
approved-text focus gate and never uses accessibility or benchmark oracle input.
`--minimum-present 0.9 --minimum-box-confidence 0.8` are uncalibrated demo
heuristics, not measured accuracy or permission.

## Destination and credentials

OpenRouter receives goals, approved literals, and screenshots. A remote Winnow
base also sends them off-host; even loopback can forward through a remote tunnel.
Establish the actual authorized destination before sending app content. Select
the API base and port explicitly; the adapter appends `/alpha/decisions` for
OpenRouter or `/v1/systemone` for Winnow. Local Winnow is not hosted JeV.

OpenRouter uses `OPENROUTER_API_KEY_FILE` or `OPENROUTER_API_KEY`. Winnow uses
`WINNOW_API_KEY_FILE` or `WINNOW_API_KEY` when authentication is required.
Precedence: `--api-key-file`, then provider key-file environment variable, then
provider key variable. Never print keys or pass them as CLI literals or URL
credentials. There is no `--api-key` flag. Keep HTTP bodies out of diagnostics.

Image limits, malformed responses, unsupported capabilities, service errors,
and refused actions must remain visible failures. Model beliefs do not authorize
an action or prove that its target was hit.
