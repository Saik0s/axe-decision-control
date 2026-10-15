# Provider contracts

JeV 1.14 provider facts were verified for this project against primary sources
and a live gateway probe on **2026-10-15**; local adapter contracts were checked
for this update. Other provider evidence below retains its 2026-10-05 review.
**Published capability and source support are not runtime proof.** Historical
hosted/local typed probes, contrasting-image probes and local function-call
validation are separate evidence.
The [results](results.md) distinguish measured inference, native outcomes and
unsupported pairs. A successful probe does not establish general model adherence,
account availability or a deployed service for another checkout.

## Identity and supported routes

| Selection | Package route | Boundary |
| --- | --- | --- |
| OpenRouter `typesafe/jev-1.14` | `/alpha/decisions` | Text/image decisions and experimental boxes; tree/grid/box default |
| OpenRouter `cloudflare/clef` | `/alpha/decisions` | Text/image decisions; hosted contrasting-image probe passed |
| OpenRouter `typesafe/jev-1.13` | `/alpha/decisions` | Historical text-only adapter route; rejects images, boxes, and direct generation |
| Winnow `Winnow-12B` | `/v1/systemone` and `/v1/chat/completions` | Caller-managed service; images need matching projector |

OpenRouter's base is `https://openrouter.ai/api`; Winnow's configurable base is
`http://127.0.0.1:8091`. These are API bases, not full endpoint paths. A custom
base must preserve the adapter's route shape. Select your service port explicitly;
recorded benchmark ports do not change the portable default. See [usage](usage.md)
for exact CLI/library configuration.

Winnow's `local` identity flag describes the configured endpoint: loopback IP
addresses and `localhost` are local; remote names, private-network addresses and
wildcard addresses are not. This classification does not perform a connectivity
check. A loopback proxy or tunnel can forward requests elsewhere, so `local=true`
does not establish the underlying model host or that data stays on this machine.

The selected JeV version is OpenRouter `typesafe/jev-1.14`. Its model page and
endpoint metadata advertise **text + image input → decisions**, and the adapter
requires the exact resolved identity `typesafe/jev-1.14-20261014` with provider
`typesafe`. The project's 2026-10-15 live `/alpha/decisions` probe returned
HTTP 200 with an actual box from text/image state and Noul/Box questions. This
establishes that concrete provider request, not simulator task success.
[JeV 1.14 model](https://openrouter.ai/typesafe/jev-1.14),
[endpoint metadata](https://openrouter.ai/api/v1/models/typesafe/jev-1.14/endpoints).

The historical `typesafe/jev-1.13` adapter route accepts its selected ID or
`typesafe/jev-1.13-20260917` and remains text-only here. This is a local contract,
not a claim about current upstream 1.13 image support. The moving
`~typesafe/jev-latest` is not a package-supported substitute. Direct TypeSafe
selectors `jev-1.14.0` and `jev-preview` belong to a different API; its latest-alias
documentation still names 1.13 in the project's 2026-10-15 source review. This package
uses the versioned OpenRouter selection rather than that alias. JeV returns
decisions, not prose or reasoning traces.

Clef is Cloudflare's multimodal decision model, based on Qwen3.8-27B. OpenRouter
currently warns that Workers AI reads roughly the first **2K text-state tokens**,
despite a 65,536-token catalog context; images count separately. Keep critical
goal/state information compact. This is a hosted warning, not a measured package
limit. [Clef gateway model page](https://openrouter.ai/cloudflare/clef).

## Hosted typed decisions

The adapter posts bearer-authenticated JSON to
`https://openrouter.ai/api/alpha/decisions`. The core body contains `model`,
`state`, and `questions`. State is text, an object, or an array. Questions are
keyed by caller-selected IDs; Noul asks whether a condition holds, Choice selects
among named criteria, and Score uses an ordered criteria array.
[Decisions reference](https://openrouter.ai/docs/api/api-reference/alphadecisions/submit-a-decisions-request).

The package narrows question instructions and criterion descriptions to strings.
Its limits are 1–64 questions for Clef and 1–256 for JeV, 2–64 Choice alternatives,
and at most 10 Score levels for Clef. These are adapter/contracts limits, not a
claim that every upstream API has identical limits. Tree/grid use Choice and Noul;
box adds Box questions for localization and Noul questions for target presence.

Response validation requires `model`, matching `answers`, and usage token counts.
`provider` is required and checked for JeV 1.14; it is optional for other routes.
Reported cost is optional. Noul has a finite yes-belief in [0, 1]
and no separate confidence. Choice needs the selected option and full probability
map; Score additionally needs a matching zero-based legend and expected value.
The gateway's generated schemas make some distribution/legend fields optional,
but this adapter requires them for its strict validation. A valid but reduced
gateway answer can therefore fail here; missing metrics are never fabricated.
[Pinned Choice schema](https://github.com/OpenRouterTeam/python-sdk/blob/9b7dcf5d79fe36e037a394a74835bbfca56dcbd8/src/openrouter/components/decisionschoiceanswer.py),
[pinned Score schema](https://github.com/OpenRouterTeam/python-sdk/blob/9b7dcf5d79fe36e037a394a74835bbfca56dcbd8/src/openrouter/components/decisionsscoreanswer.py).

The current adapter validates finite/range values, exact keys, membership, and
total mass, then normalizes Choice/Score mass and checks the winning Choice option.
Hosted mass tolerance is `K * 0.5 * 10**(-d) + 1e-6`, with d=3 for Clef and d=2
for JeV. Score must lie within the criteria range and match a unit-sum distribution
whose probabilities lie within half a rounding unit of each supplied value,
clipped to [0, 1]. Its expected-value bounds also allow half a rounding unit for
the supplied score, plus 1e-6 for arithmetic. **These are implementation
assumptions, not official hosted rounding guarantees.** Unrounded Score answers
retain mass tolerance 1e-5 and tolerance 1e-4 against the normalized expected value.
Provider confidence stays optional and unchanged. No hosted Clef confidence
formula or calibrated control threshold is established by this package.
[Current validation](../src/axe_control/providers/base.py),
[hosted adapter](../src/axe_control/providers/openrouter.py).

## Images

OpenRouter Clef and JeV 1.14 send `state` as content parts: a text part containing
serialized state followed by `image_url` parts with still-image data URLs.
The generated gateway request allows an array; model metadata advertises image
input. The project's 2026-10-15 JeV probe used this encoding with Noul/Box questions.
For Clef, a hosted counterprobe with identical text/questions and red/blue images
selected the matching color in both cases. This proves the concrete encoding
works for that probe, not general visual grounding accuracy. There is no top-level `images` member
in this gateway request schema. [Pinned request schema](https://github.com/OpenRouterTeam/python-sdk/blob/9b7dcf5d79fe36e037a394a74835bbfca56dcbd8/src/openrouter/components/decisionsrequest.py),
[Clef model page](https://openrouter.ai/cloudflare/clef).

The hosted adapter's common byte limits are at most 4 images, 4 MiB decoded
per image, 8 MiB decoded total, and 6 MiB encoded per image. Shared HTTP bodies are
bounded to 32 MiB; Clef decisions additionally have a 13 MiB serialized body cap.
Clef accepts PNG/JPEG/WebP data URLs. These are local validation limits.
Direct Workers AI is a different API, uses top-level `images`, and has its own
limits/envelope; this
package does not implement that route. [Cloudflare Clef API](https://developers.cloudflare.com/workers-ai/models/clef/).

JeV 1.14 image requests opt in with `TypeSafe-Danger-Zone-Images: true`, supplied
automatically by this adapter. TypeSafe documents PNG/JPEG, each side in
**256–1568 pixels**, and area in **78,400–2,458,624 pixels**, with inclusive limits.
This adapter uses a more conservative **280-pixel minimum side**. In the project's
2026-10-15 gateway probe, a 278×394 image satisfying the published bounds received
HTTP 400, while 280×397 was accepted. The 280 floor is an empirical compatibility
guard, not a revised upstream specification or a guarantee of acceptance.
The adapter safely decodes inputs, resizes while preserving aspect ratio apart
from integer rounding, and emits metadata-free PNG. It can upscale small grid
crops within its 280–1568 side bounds and the published area limits, or downscale
large screenshots. Impossible aspect ratios, malformed inputs, and invalid
prepared dimensions are rejected before
HTTP; prepared images are also rechecked against the common byte limits.
The historical JeV 1.13 route rejects images before HTTP.
[TypeSafe image contract](https://docs.typesafe.ai/images),
[image preparation](../src/axe_control/providers/jev_images.py).

Winnow decisions send images in `winnow.images`; chat uses `messages[].content`
image parts. The pinned native API requires still-image data URLs, not remote
URLs or file paths, with a matching projector, at most 16 images, 24 MiB encoded
per image, and 32 MiB for the entire body. Context/preprocessing capacity also
applies. [Pinned Winnow API](https://github.com/EldanRing/winnow-inference/blob/77d14580c6732ca2f3745750c1dc1fd446d8bcee/docs/API.md).

Winnow's Python capability flag defaults to vision enabled; CLI construction does
not discover server capabilities. A flag, model file, listening port, or health
response is not vision proof. Use `vision=False` in the library for text-only
serving and obtain image evidence before a grid run.

## Experimental box decisions

TypeSafe describes Box as experimental, “dreamer-ready.” An answer contains
`box: {top, bottom, left, right}` and `confidence`. All coordinates and confidence
must be finite numbers in [0, 1], with `left < right` and `top < bottom`.
Coordinates are normalized to the submitted image, not simulator points.
**A box is returned even when the target is absent**, so localization must be
paired with a Noul presence question. Confidence alone does not establish
visibility or a safe hit. [Official Box primitive](https://docs.typesafe.ai/primitives/box).

Only JeV 1.14 exposes `capabilities.boxes` in the bundled adapters. Box questions
require an image and a box-capable provider; unsupported requests are rejected
before HTTP. The box planner receives screenshots, geometry, goal, approved
literals, history, and optional caller-supplied control descriptions, with no
accessibility state or benchmark oracle. `Task.target_descriptions` defaults to
an empty list and is populated by repeated CLI `--target` options. Only box uses
it: a typed Choice target question accompanies operation selection, and the
selected description becomes the explicit subject for Box and Noul questions.
Approved literal focus rules still apply. Generic localization without targets
remains supported; narrow descriptions reduce ambiguity without establishing
reliability. Noul asks about visible presence; Box requests an enabled control
with an unobstructed center.

If initial presence and confidence are both at least 0.5, but either is below its
configured final gate, localization gets **one** closer crop request. The crop
pads each edge by 6% of full-image width/height, clips to the screenshot, and
retains the same target. The crop is enlarged 2×, then the adapter prepares it
within its 280–1568 side bounds and area limits. Crop-relative returned edges map
back to full-image normalized coordinates before logical-point conversion. A score below
0.5 skips refinement. The extra request consumes the existing model budget;
refinement does not lower the final presence/confidence gates.

After fresh-screen verification, the runner gates taps on Noul presence
(`--minimum-present`, default 0.9) and box confidence
(`--minimum-box-confidence`, default 0.8). These are **uncalibrated demo
heuristics**, not calibrated probabilities or safety guarantees. The normalized
center becomes logical points via `x = (left + right) / 2 * point_width` and
`y = (top + bottom) / 2 * point_height`. Approved text and preceding focus-tap
rules are shared with grid. See [architecture](architecture.md#planner-boundaries)
and [box usage](usage.md#experimental-box-control).

## Local decisions and actual function calls

Winnow decision requests add `winnow.diagnostics=true` and `reuse_prefix` to
the common body. Decisions return zero output tokens; logical input counts
include repeated submitted questions, while physical prefix work is separate.
Its candidate probabilities are conditional on the supplied alternatives.
Choice/Score confidence is `1 - entropy(p)/log(K)`, a concentration measure,
not a correctness guarantee. A compatible request shape does not reproduce
JeV's weights, calibration, or hosted service. [Pinned scoring implementation](https://github.com/EldanRing/winnow-inference/blob/77d14580c6732ca2f3745750c1dc1fd446d8bcee/native/protocol.h).

The direct planner uses `/v1/chat/completions`, a function schema named
`simulator_action`, `parallel_tool_calls=false`, and nonstreaming responses.
OpenRouter requests that named function; Winnow uses string `tool_choice=required`
for its pinned parser. Both adapters require exactly one returned function call
and validate its JSON arguments. Plain JSON message content does not count as a
tool call. Winnow serving must enable the required chat template/tool parser;
upstream documents `--jinja`. The local setup validated two actual returned calls;
every later call still requires independent argument validation before execution.
[Pinned llama.cpp function calling](https://github.com/ggml-org/llama.cpp/blob/911f6cdc8ab8a530b2bee09ee61471a6f3178eeb/docs/function-calling.md),
[current adapters](../src/axe_control/providers/).

Generative models receive no host shell/filesystem tools. The host executes only
validated simulator actions. Direct's actual HTTP requests, including fresh
completion calls, use the same request budget as typed decisions. HTTP default
timeout is 90 seconds; requests have no automatic retry. Deadline/cancellation
checks are cooperative between calls, as described in [architecture](architecture.md).

## Data and telemetry

Use provider credential environment variables or `--api-key-file`, as documented
in [usage](usage.md#provider-and-credentials). Do not place credentials in the base
URL; query strings, fragments, and URL userinfo are rejected. The HTTP client does
not follow redirects or inherit environment proxies. No raw body/error payload
is included in default errors or reports.

Cloud requests include goals, literals, and app content, plus screenshots for
grid/box and caller target descriptions for box. The caller must authorize that
destination; a belief score grants no permission. Selecting a remote Winnow base
also sends data off-host. Reports
retain numeric usage/timing/cache metrics and bounded identity/status metadata,
not private content, target descriptions, or credentials. Box events include
numerical normalized bounds, presence belief, confidence, and tap points, without screenshots by
default. Optional cost stays unknown when missing;
hosted output-token counts are preserved. Backend allocated bytes are a
device/backend observation, not per-request peak memory. Explicit capture through
`observe` persists content and is separate from telemetry.

The [JeV demo recorder](../tools/record_jev_demos.py) explicitly
captures synthetic screenshots, recordings, state/questions/responses for
tree/grid/box demos and makes paid calls. Repeated recorder `--target` options
pass descriptions to box only; those descriptions can appear in explicit capture
records, unlike default reports. The same goal and initial state do not make
these a **controlled benchmark**, because box receives additional workflow
guidance. Embedded image bytes are not stored in question records. This capture
path is separate from ordinary
telemetry. The 2026-10-15 [prototype observations](usage.md#recorded-prototype-observations-2026-10-15)
record independent passes for tree (8 calls, 12.216 s), grid (22 calls, 26.452 s),
and [final image-fix box](../results/jev-1.14-2026-10-15/box-image-fix/box/episode.json)
(18 calls, 24.056 s), with `Episode.issues() == []` and unchanged box gates.
All share the “Review PR / 50 minutes / Quiet mode on” synthetic goal and initial
state; these are prototype observations, not a broad benchmark. Three generic-box
attempts are retained, with presence uncertainty around 0.81–0.89 correctly blocked by the
unchanged gate. A successful provider probe alone does not establish native
task success. The frozen 2026-10-05
[105-episode comparison](results.md#native-control-2026-10-05), including
Clef/Winnow's 0/30 strict grid passes, does not measure JeV 1.14 grid/box performance.

## Provenance and licenses

- Clef's published weights/helper declare **Apache-2.0**, base Qwen3.8-27B.
  Source pin `2f3de3dd85f379784083b0814d997ab627200f0c` identifies published
  artifacts, not a pinned hosted deployment. [Pinned Clef card](https://huggingface.co/Cloudflare/clef/blob/2f3de3dd85f379784083b0814d997ab627200f0c/README.md).
- JeV is **proprietary and hosted**; published weights are not established.
  Never label a local Winnow compatibility endpoint as local JeV.
  [OpenRouter's JeV explanation](https://openrouter.ai/blog/insights/what-is-jev/).
- Winnow inference code is **MIT**; merged Winnow-12B weights/projector declare
  **Apache-2.0**, based on Gemma 4 12B IT. Code and weights have separate notices.
  [Inference license](https://github.com/EldanRing/winnow-inference/blob/903f43054b706ba9f0a012cb507a6ed66e6c2f42/LICENSE),
  [pinned weight card](https://huggingface.co/EldanRing/Winnow-12B/blob/abb21621114b10690259a7517fa59b153675176e/README.md).

The local API reference above is pinned to Winnow commit
`77d14580c6732ca2f3745750c1dc1fd446d8bcee`, with llama.cpp reference
`911f6cdc8ab8a530b2bee09ee61471a6f3178eeb`. Newer Winnow release `v2026.10.04`
has different launch defaults and optional modes; do not assume an older service
has them. Its release recommends corrected `notices1` archives rather than
automatic tag archives; the distributed Linux/CUDA runtime is not a Mac binary.
[Release provenance](https://github.com/EldanRing/winnow-inference/releases/tag/v2026.10.04).

Record the actual selected model, service/runtime revision, and model/projector
hashes when gathering evidence. Upstream benchmarks and published assets are
not package benchmarks, installed-service readiness, or native outcome proof.
