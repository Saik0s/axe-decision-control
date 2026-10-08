# Local Winnow setup and measured readiness

The measured Winnow-12B service passed synthetic text/image decisions and actual
function-call validation. The [local inference results](../results/local-performance/)
include 66 attempts against that resident service. Setup probes described below
test inference and wire compatibility; native task outcomes are evaluated by the
separate [simulator benchmark](benchmarks.md).

## Pinned assets and runtime

The measurements reused an existing executable at the following source pins.
The fresh-checkout instructions below build the pinned runtime separately from
this wrapper. Model weights and native server binaries are not bundled here.

- Winnow source: `77d14580c6732ca2f3745750c1dc1fd446d8bcee`.
- Patched llama.cpp source: `911f6cdc8ab8a530b2bee09ee61471a6f3178eeb`.
- Native executable: `${WINNOW_ROOT}/.build/bin/winnow-server`.
- Q8 weights: `EldanRing/Winnow-12B/gguf/Winnow-12B-Q8_0.gguf`,
  **12,669,646,592 bytes**, SHA-256
  `b710efc4c0d048ee61eed92c5fef5ce323a4d17e7c51f9f0533cc72ae50818ea`.
  The weight hash comes from the prior verified research; this setup checked
  the current size and loaded that file, without repeating its full hash.
- Projector: `gguf/mmproj-Winnow-12B.gguf`, **175,115,840 bytes**, SHA-256
  `91f086971e56d7a7d8d39e271873fccdb49541bd259d6e02c401a4f1cb7a219e`.
  This setup downloaded it from revision
  `abb21621114b10690259a7517fa59b153675176e` and verified size and SHA-256 before
  launch. Existing files were preserved.

Primary pins: [launcher source](https://github.com/EldanRing/winnow-inference/blob/77d14580c6732ca2f3745750c1dc1fd446d8bcee/scripts/serve.py),
[runtime lock](https://github.com/EldanRing/winnow-inference/blob/77d14580c6732ca2f3745750c1dc1fd446d8bcee/runtime.lock.json),
[model release manifest](https://huggingface.co/EldanRing/Winnow-12B/resolve/abb21621114b10690259a7517fa59b153675176e/release-manifest.json),
[exact projector](https://huggingface.co/EldanRing/Winnow-12B/resolve/abb21621114b10690259a7517fa59b153675176e/gguf/mmproj-Winnow-12B.gguf).

## Portable setup commands

On Apple Silicon, install Xcode command-line tools, Git, CMake and OpenSSL before
building. The [pinned upstream installation guide](https://github.com/EldanRing/winnow-inference/blob/77d14580c6732ca2f3745750c1dc1fd446d8bcee/docs/INSTALL.md)
documents prerequisites and the distinct Linux/CUDA path. Setup downloads about
12.85 GB and needs additional source/build space; upstream suggests 20 GB free
as a starting allowance. This wrapper does not install system packages.

Set `WINNOW_ROOT` to a new checkout path and `MODEL_STORE_ROOT` to a directory
you own. If you already have the pinned checkout, skip clone/checkout and confirm
its revision with `git rev-parse HEAD`. Do not switch an unrelated working tree.

```sh
rtk proxy git clone https://github.com/EldanRing/winnow-inference.git "$WINNOW_ROOT"
rtk proxy git -C "$WINNOW_ROOT" checkout --detach 77d14580c6732ca2f3745750c1dc1fd446d8bcee
rtk proxy uv run --offline --no-project python -B "$WINNOW_ROOT/scripts/setup.py" \
  --profile apple-silicon \
  --model-dir "$MODEL_STORE_ROOT/EldanRing/Winnow-12B" --jobs 4
```

The upstream downloader verifies existing complete files and resumes partial
downloads; a checksum mismatch stops rather than overwriting a complete file.
Its pinned manifest calls the projector `mmproj-F16.gguf`. The measured service
used the earlier filename `mmproj-Winnow-12B.gguf`; the recorded size and SHA-256
above are identical. For a fresh setup, use the manifest filename below.

To verify an existing earlier projector without replacing it:

```sh
rtk proxy uv run --offline --no-project python -B - <<'PY'
import hashlib
import os
import urllib.request
from pathlib import Path

directory = Path(os.environ["MODEL_STORE_ROOT"]) / "EldanRing/Winnow-12B/gguf"
projector = directory / "mmproj-Winnow-12B.gguf"
revision = "abb21621114b10690259a7517fa59b153675176e"
url = (
    "https://huggingface.co/EldanRing/Winnow-12B/resolve/"
    + revision + "/gguf/mmproj-Winnow-12B.gguf"
)
if not projector.exists():
    with urllib.request.urlopen(url, timeout=45) as response, projector.open("xb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
with projector.open("rb") as source:
    checksum = hashlib.file_digest(source, "sha256").hexdigest()
if (
    projector.stat().st_size != 175115840
    or checksum != "91f086971e56d7a7d8d39e271873fccdb49541bd259d6e02c401a4f1cb7a219e"
):
    raise SystemExit("Projector verification failed; existing file preserved")
print("Projector size and SHA-256 verified")
PY
```

Launch in a free loopback port and keep this terminal open. These explicit
8,192-token settings match the measured configuration; upstream's profile
defaults can differ. `WINNOW_PORT` defaults to the wrapper's 8091. The recorded
run selected 8093 explicitly, which is not a required port.

```sh
rtk proxy uv run --offline --no-project python -B \
  "${WINNOW_ROOT}/scripts/serve.py" \
  --server "${WINNOW_ROOT}/.build/bin/winnow-server" \
  --model "${MODEL_STORE_ROOT}/EldanRing/Winnow-12B/gguf/Winnow-12B-Q8_0.gguf" \
  --mmproj "${MODEL_STORE_ROOT}/EldanRing/Winnow-12B/gguf/mmproj-F16.gguf" \
  --alias Winnow-12B --profile apple-silicon \
  --context 8192 --decision-context 8192 \
  --cache f16 --memory exclusive \
  --decision-parallel 1 --chat-parallel 1 \
  --batch 2048 --ubatch 1024 --host 127.0.0.1 --port "${WINNOW_PORT:-8091}" \
  --log-disable
```

The measured launch used a minimal environment and did not inherit provider
credentials or environment-driven host tools. Do not enable
`--tools` or `--agent` for the client action baseline. Logs are disabled so
future private simulator content is not captured by server logging.

Readiness and model discovery:

```sh
rtk proxy curl --fail --silent --show-error "http://127.0.0.1:${WINNOW_PORT:-8091}/health"
rtk proxy curl --fail --silent --show-error "http://127.0.0.1:${WINNOW_PORT:-8091}/v1/models"
```

For the measured service, both returned HTTP 200. Discovery identified `Winnow-12B`, Q8_0, 8192 configured
context, and `completion` plus `multimodal` capabilities. Native inspection
identified `gemma4`, device `Apple M2 Ultra`, vision enabled, F16 cache, selected
decision head, optimized pipeline, batch 2048, ubatch 1024, and one decision
branch. Its runtime fingerprint was
`21e6e69d8e43e318089e77459d102f05ee2cad266999c7860e64048f69c89e84`.

## Runtime observations

On 2026-10-05, the host was an Apple M2 Ultra with **64 GiB** unified memory.
Requests were sequential and used synthetic inputs only.

| Probe | Observed result | HTTP request time |
| --- | --- | --- |
| Text decision | Expected WAIT selected; 125 input tokens, 0 output tokens | 961.68 ms |
| Image decisions | Red and blue both selected correctly; 81 image tokens each | 723.52 / 592.38 ms |
| Valid native function calls | Exact bounded TAP validated twice; 29 completion tokens each | 1770.98 / 767.28 ms |

The two 256-by-256 PNG images were generated in memory. The image requests had
identical state, question, criteria, and options; only the image data URL
changed. `reuse_prefix` was false, both reported zero prefix reuse, and both
returned the expected color. This establishes sensitivity to these contrasting
images, rather than general simulator screenshot accuracy.

The successful chat requests each returned exactly one
`choices[0].message.tool_calls` entry, `type: function`, function name
`simulator_action`, a nonempty call ID, and `finish_reason: tool_calls`.
`Action.model_validate_json()` accepted the returned argument string, and the
probe checked the exact expected TAP point and absence of target/text. No
JSON-action fallback, server-side execution, or AXe action was used.

**Initial failure remains relevant:** the first prompt produced a native tool
call with `point` as an array, which failed the Action validator. A repeat
confirmed that failure. Explicitly describing `point` as an object with numeric
`x` and `y`, and presenting synthetic geometry in that shape, produced the two
valid calls. The full Action schema and server/template configuration were
unchanged. These two successes establish the bounded case, not universal
schema adherence; validate every returned action before execution.

Source review confirms the reason: Gemma 4's native grammar constrains the
function name and call count but uses generic argument values and does not
compile `function.parameters` into argument constraints. Passing the schema to
the model therefore does not enforce its Point object shape.
Source: [Gemma 4 native tool grammar](https://github.com/ggml-org/llama.cpp/blob/911f6cdc8ab8a530b2bee09ee61471a6f3178eeb/common/parsers/gemma4.cpp#L248).

For this installed runtime, use **`tool_choice: "required"`** and
**`parallel_tool_calls: false`** with one `simulator_action` function whose
parameters are `Action.model_json_schema()`. The installed launcher already
enables `--jinja`. Its parser accepts the string modes `auto`, `none`, and
`required`; the named-function object form is incompatible with this pin.
Source: [tool-choice parser](https://github.com/ggml-org/llama.cpp/blob/911f6cdc8ab8a530b2bee09ee61471a6f3178eeb/common/chat.cpp#L345).

## Resource evidence and limits

Across the recorded requests, sampled process RSS peaked at
**14,177,665,024 bytes / 13.204 GiB**. The sampled physical footprint peaked at
**1,948,249,272 bytes / 1.814 GiB**. Decision diagnostics reported backend
allocation up to **14,664,105,984 bytes / 13.657 GiB**, against a reported backend
budget of **55,662,788,608 bytes / 51.840 GiB**. These measurements describe
different accounting views and must not be added together or substituted for
each other.

The resource sampler used `proc_pid_rusage` for the owned PID every 0.1 seconds,
plus boundary samples. Peaks are sampled lower bounds. CPU values required the
host's Mach timebase conversion of **125/3 nanoseconds per tick**. A local CPU
calibration matched `time.process_time()` at approximately 0.150 seconds.
The original request-resource artifacts predate this correction and label raw
Mach ticks as nanoseconds. **`resource-summary.json` is authoritative for their
corrected CPU values**; originals are preserved, and `resources.py` now converts
the ticks before reporting. [Apple's rusage accounting source](https://github.com/apple-oss-distributions/xnu/blob/main/osfmk/kern/bsd_kern.c#L1196)
connects these fields to task accounting; [Recount documentation](https://github.com/apple-oss-distributions/xnu/blob/main/doc/observability/recount.md)
describes Mach time units.

Corrected total process CPU time was 0.306 seconds for text, 0.073/0.064 seconds
for red/blue, and 0.211/0.088 seconds for the two valid tool calls. GPU utilization,
power, and energy were not sampled. Host swap was already approximately
**6481.56 MiB used** at the first probe's end; that is host-wide state, not
attributed to this process.

The first valid tool request processed 230 prompt tokens; the repeat reused
225 cached prompt tokens. Decision and chat contexts switch under the
`exclusive` memory policy. These are a few setup observations with different
warm/cache states, not percentiles, capacity tests, or simulator benchmarks.

Configured decision and chat contexts are **8192 tokens**, despite model
metadata advertising a **262,144-token trained context**. One chat slot and one
decision branch were tested. Installed decision limits are **1-256 questions**,
**2-64 alternatives per question**, and **at most 16 images**. Each image must
be a base64 image data URL; its encoded base64 portion is limited to
**24 MiB**, and the patched HTTP body limit is **32 MiB**. Images count against
the configured context. Decision images go in `winnow.images`; chat images use
`messages[].content` image parts. Vision chat generation, streaming, JSON-only
generation, concurrency, and context exhaustion were not exercised here.
Sources: [decision protocol](https://github.com/EldanRing/winnow-inference/blob/77d14580c6732ca2f3745750c1dc1fd446d8bcee/native/protocol.h),
[image parser](https://github.com/EldanRing/winnow-inference/blob/77d14580c6732ca2f3745750c1dc1fd446d8bcee/native/images.h),
[patched HTTP server](https://github.com/EldanRing/winnow-inference/blob/77d14580c6732ca2f3745750c1dc1fd446d8bcee/patches/llama-winnow-server.patch).

## Benchmark provenance

Historical setup records are retained locally under the ignored path
`.agents/runtime/tasks/reusable-control/artifacts/local-winnow/`:

- `projector.json`: pinned download, current byte count, and verified hash.
- `launch.json`: actual owned PID and launch configuration, binary/source identity.
- `observations.json`: health/model/backend identity and text/image observations;
  initial function-call failure remains present.
- `tool-call-observations.json`: the initial failure and two later validated calls.
- `resource-summary.json`: corrected resource metrics with references to original
  per-request samples; `resource-calibration.json` establishes CPU conversion.
- `final-health.json`: final GET checks and owned executable identity.
- `handoff.json`: final verdict, scope limits, and service availability.

Those setup records are not the shareable benchmark dataset. The public
[local results](../results/local-performance/results.json) retain measured host,
allowlisted service discovery, declared launch pins and per-attempt numeric
diagnostics without private executable/weight paths. Choose your own service
URL and model ID for a new run. Hosted costs, GPU energy and general application
accuracy are not established by local setup probes.
