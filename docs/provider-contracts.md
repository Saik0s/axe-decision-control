# Provider contracts

Reviewed against current adapters and primary sources on 2026-10-05. **Published
capability and source support are not runtime proof.** Hosted/local typed probes,
contrasting-image probes and local function-call validation have been executed.
The [results](results.md) distinguish measured inference, native outcomes and
unsupported pairs. A successful probe does not establish general model adherence,
account availability or a deployed service for another checkout.

## Identity and supported routes

| Selection | Package route | Boundary |
| --- | --- | --- |
| OpenRouter `cloudflare/clef` | `/alpha/decisions` | Text/image decisions; hosted contrasting-image probe passed |
| OpenRouter `typesafe/jev-1.13` | `/alpha/decisions` | Text decisions only; reject images and direct generation |
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

The adapter allows the Jev response identity `typesafe/jev-1.13-20260917` for the
requested `typesafe/jev-1.13`; other resolved IDs must match the requested model.
This reflects the [gateway response example](https://openrouter.ai/docs/api/api-reference/alphadecisions/submit-a-decisions-request).
The moving `~typesafe/jev-latest` and direct TypeSafe selectors are separate
names, not package-supported substitutes. Jev returns decisions, not prose or
reasoning traces. Its gateway input is text with a listed 32,000-token context.
[OpenRouter Jev guide](https://openrouter.ai/docs/guides/community/jev).

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
Its limits are 1–64 questions for Clef and 1–256 for Jev, 2–64 Choice alternatives,
and at most 10 Score levels for Clef. These are adapter/contracts limits, not a
claim that every upstream API has identical limits. Tree/grid use Choice and Noul.

Response validation requires `model`, matching `answers`, and usage token counts.
`provider` and reported cost are optional. Noul has a finite yes-belief in [0, 1]
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
for Jev. Score must lie within the criteria range and match a unit-sum distribution
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

OpenRouter Clef currently sends `state` as content parts: a text part containing
serialized state followed by `image_url` parts with still-image data URLs.
The generated gateway request allows an array; model metadata advertises image
input. A hosted counterprobe with identical text/questions and red/blue images
selected the matching color in both cases. This proves the concrete encoding
works for that probe, not general visual grounding accuracy. There is no top-level `images` member
in this gateway request schema. [Pinned request schema](https://github.com/OpenRouterTeam/python-sdk/blob/9b7dcf5d79fe36e037a394a74835bbfca56dcbd8/src/openrouter/components/decisionsrequest.py),
[Clef model page](https://openrouter.ai/cloudflare/clef).

The hosted adapter accepts PNG/JPEG/WebP data URLs, at most 4 images, 4 MiB decoded
per image, 8 MiB decoded total, and 6 MiB encoded per image. Shared HTTP bodies are
bounded to 32 MiB. These are local validation limits. Direct Workers AI is a
different API, uses top-level `images`, and has its own limits/envelope; this
package does not implement that route. [Cloudflare Clef API](https://developers.cloudflare.com/workers-ai/models/clef/).
Jev cannot acquire vision by receiving an array of image descriptors.

Winnow decisions send images in `winnow.images`; chat uses `messages[].content`
image parts. The pinned native API requires still-image data URLs, not remote
URLs or file paths, with a matching projector, at most 16 images, 24 MiB encoded
per image, and 32 MiB for the entire body. Context/preprocessing capacity also
applies. [Pinned Winnow API](https://github.com/EldanRing/winnow-inference/blob/77d14580c6732ca2f3745750c1dc1fd446d8bcee/docs/API.md).

Winnow's Python capability flag defaults to vision enabled; CLI construction does
not discover server capabilities. A flag, model file, listening port, or health
response is not vision proof. Use `vision=False` in the library for text-only
serving and obtain image evidence before a grid run.

## Local decisions and actual function calls

Winnow decision requests add `winnow.diagnostics=true` and `reuse_prefix` to
the common body. Decisions return zero output tokens; logical input counts
include repeated submitted questions, while physical prefix work is separate.
Its candidate probabilities are conditional on the supplied alternatives.
Choice/Score confidence is `1 - entropy(p)/log(K)`, a concentration measure,
not a correctness guarantee. A compatible request shape does not reproduce
Jev's weights, calibration, or hosted service. [Pinned scoring implementation](https://github.com/EldanRing/winnow-inference/blob/77d14580c6732ca2f3745750c1dc1fd446d8bcee/native/protocol.h).

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
grid. The caller must authorize that destination; a belief score grants no
permission. Selecting a remote Winnow base also sends data off-host. Reports
retain numeric usage/timing/cache metrics and bounded identity/status metadata,
not private content or credentials. Optional cost stays unknown when missing;
hosted output-token counts are preserved. Backend allocated bytes are a
device/backend observation, not per-request peak memory. Explicit capture through
`observe` persists content and is separate from telemetry.

## Provenance and licenses

- Clef's published weights/helper declare **Apache-2.0**, base Qwen3.8-27B.
  Source pin `2f3de3dd85f379784083b0814d997ab627200f0c` identifies published
  artifacts, not a pinned hosted deployment. [Pinned Clef card](https://huggingface.co/Cloudflare/clef/blob/2f3de3dd85f379784083b0814d997ab627200f0c/README.md).
- Jev is **proprietary and hosted**; published weights are not established.
  Never label a local Winnow compatibility endpoint as local Jev.
  [OpenRouter's Jev explanation](https://openrouter.ai/blog/insights/what-is-jev/).
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
