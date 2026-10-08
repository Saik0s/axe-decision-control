# Local inference performance benchmark

Run from the repository root with the existing server. This benchmark does not
launch, restart, reconfigure or stop it, and never controls a simulator. The
caller owns live inference and native runs. An executed 66-attempt run is included
in [results/local-performance](../results/local-performance/), with all 60 measured
attempts and six setup attempts preserved. Every measured cache regime passed.
Offline tests establish the harness contracts separately from those measurements.

```sh
rtk proxy uv run python -m benchmarks.inference \
  --base-url http://127.0.0.1:8093 --model Winnow-12B \
  --server-pid PID --repeats 5 --output benchmark-runs/local-performance-RUN
```

Replace `PID` with the currently owned server PID and choose a new output
directory for each run. Even an existing empty directory is rejected before any
GET or inference request. Only loopback URLs without credentials, queries,
fragments or paths are accepted. The timeout is **180 seconds per request**;
override with `--timeout-seconds`. Repetitions may be **1–100**, but a series
needs **at least 3 valid samples** to verify a regime. The CLI returns **0** only
when every cold and warm series is verified; otherwise **2**, retaining a report
when discovery or measured requests failed.

The module is a repository benchmark, not a wheel-installed CLI entry point.
Its only dependencies are the package's existing HTTP, schema and image libraries.

## Workloads and schedule

Six cases use deterministic structured state and PNGs generated in memory:

- Text small: **4 synthetic controls, 1 question**.
- Text medium: **24 controls, 8 questions**.
- Text large: **64 controls, 16 questions**.
- Text many: **24 controls, 32 questions**.
- Image square: **256 × 256 PNG, 4 controls, 1 question**.
- Image phone portrait: **402 × 874 PNG, 12 controls, 4 questions**.

The serialized state is capped at **7,000 UTF-8 bytes**, with short questions,
to leave room in the intended **8,192-token** context. This is an input bound,
not a token estimate or a guarantee for arbitrary tokenizers or smaller server
contexts. Actual response `input_tokens`, `image_tokens`, prefix and suffix
tokens are recorded when available. A context-limit error remains a failed
attempt. Winnow's logical input accounting can include all submitted question
suffixes; it should not be mistaken for a single branch's occupied context.

Every question has distinct instructions, including its check index. The harness
records submitted question count, distinct serialized question count, and native
`unique_questions` when reported. A native count that differs from submitted
count invalidates the sample. This avoids measuring a batch of duplicate
questions whose physical work the backend can deduplicate.

Each case runs sequentially: **5 prefix-cold attempts**, then **1 warm setup
attempt**, then **5 warm measured attempts**. At the default, there are **66
attempts**, **60 measured and 6 setup**. State, questions and image bytes are
identical within a case; only the prefix-reuse option changes. There is no retry,
parallel client load, question adaptation, fixture oracle, private content or
calibrated quality evaluation. Typed answer validation proves valid schemas and
matching question IDs, not whether the model's judgments are correct.

## Verified cache regimes

Cold sends `reuse_prefix=false` on every attempt and requires diagnostics
`prefix_reused_tokens=0` and `prefix_processed_tokens>0`.

**Prefix-cold is not model-start cold or filesystem-cache cold.** The server,
weights, image processing and operating-system caches remain resident. Other
server traffic, backend tokenization caches and context evictions can affect
results. Run an owned, otherwise idle server for interpretable comparisons.

Warm setup sends `reuse_prefix=true` separately from measured repeats. Each warm
repeat requires **both `cache_hit=true` and `prefix_reused_tokens>0`**. Missing
diagnostics never prove warm reuse. A warm series also requires a successful
typed setup. Setup is preserved with its timing, costs and sampler evidence but
excluded from measured latency statistics.

A series is verified only when **every measured attempt is valid** and there
are **at least 3** such attempts. HTTP/schema failures, missing required usage,
missing image-token evidence for images, unique-count mismatches, or cache-regime
failures invalidate their samples. Valid subsets still get explicitly counted
latency summaries, but one failed attempt prevents that series from being
verified and prevents its warm/cold ratio. The ratio is **cold wall median /
warm wall median**, so a value above 1 means lower measured warm wall latency.

## Evidence and scopes

`results.json` is a strict, machine-readable record with numeric sample/case IDs,
repetition indices, exact state byte counts, numeric input/image tokens and
native diagnostics, HTTP status, typed call identity and accounting, and sampled
RSS/CPU. `report.md` is the readable summary. Neither saves transformation
state, image data, answer values, response/error bodies, credentials or paths to
weights. The numeric response allowlist is captured before adapter validation,
so HTTP errors and malformed answers can retain reported tokens/cost even when
the adapter cannot map them. Invalid numeric fields remain unknown and are
flagged; other valid numeric evidence survives. No attempt is converted into a
fabricated successful or zero-latency sample. Unreported cost is **null**, not
free; charged failed attempts and setup are included in reported accounting.

- `wall_ms` brackets `provider.decide`, excluding sampler startup/shutdown.
  It includes client serialization, HTTP, response parsing and strict validation.
- `call.usage.request_ms` is the adapter's measured HTTP/decoding duration,
  retained on failures too. It is client timing, not a server-only timer.
- `native.prefill_ms` and `native.request_prefill_ms` retain the two reported
  components; summary `provider_prefill_ms` is their adapter-mapped sum.
  Native request, decode, queue and token-work counters are server reports.
- Every request has a **whole-process** sampler window at **0.1-second** nominal
  intervals. RSS is **KiB**, CPU is `ps` percent and may exceed 100. Sampler
  `peak_rss_kib` is the maximum observed whole-process RSS in that window. It is
  neither incremental request memory nor a per-request allocation peak, and
  short peaks between polls can be missed. An explicit PID is sampled; this
  alone does not establish that the PID owns the HTTP endpoint. The operator
  must select the owned server PID. Sampling failures preserve an empty/partial
  report and fixed diagnostics without invalidating otherwise valid inference.
- `backend_allocated_bytes` and `backend_budget_bytes` describe the reported
  **backend/device** memory scope. They are neither process RSS nor request
  peaks. Apple unified memory makes adding these numbers to RSS misleading.
  CPU percent and wall time establish no calibrated energy measurement.

Latency summaries include **median, minimum, maximum, nearest-rank sample p95
and actual sample count** for every available timing metric. Missing timings
are excluded from that metric, never filled with zero. At **n=5, sample p95 is
the maximum**; five observations do not establish stable tail latency,
production capacity, concurrency limits, calibrated answer quality or energy.
Failed attempts remain in the attempt/failure denominator and raw evidence,
and their charged numeric accounting is retained, but their times do not enter
successful-latency statistics.

## Host and launch provenance

Each run measures platform, architecture, Python/package versions and logical
CPU count. On macOS it reads `machdep.cpu.brand_string` and `hw.memsize` with
`sysctl`; on other Unix hosts it attempts physical-page memory accounting.
Missing metadata remains null. The script independently GETs `/health` and
`/v1/models`, validates `status=ok` and discovery of the requested model, and
preserves allowlisted model identity/metadata such as actual `n_ctx` and `ftype`.
Failed discovery produces a report with **zero inference attempts**.

Use optional `--launch-metadata FILE.json` to record strict **operator-declared**
configuration that GET discovery cannot prove. Allowed fields are
`context_capacity`, `backend`, `device`, `quantization`, `kv_cache`,
`projector_loaded`, `parallel`, `winnow_commit` and `llama_cpp_commit`.
Unknown fields, including private executable/model paths, are rejected.

```json
{
  "context_capacity": 8192,
  "backend": "Metal",
  "device": "Apple M2 Ultra",
  "quantization": "Q8_0",
  "kv_cache": "F16",
  "projector_loaded": true,
  "parallel": 1,
  "winnow_commit": "77d14580c6732ca2f3745750c1dc1fd446d8bcee",
  "llama_cpp_commit": "911f6cdc8ab8a530b2bee09ee61471a6f3178eeb"
}
```

These are the setup pins documented in [local-winnow.md](local-winnow.md), not
facts inferred from live health, a PID, or the presence of files. That setup
documents an Apple M2 Ultra host with **64 GiB (68,719,476,736 bytes)** and a
12B Q8 model plus projector, **8,192** context and F16 KV cache. Reconfirm the
current launch before using this metadata. Host measurements, GET discovery,
operator declarations and request diagnostics remain distinct evidence.

## Offline validation

```sh
rtk proxy uv run pytest -q tests/test_inference.py
rtk proxy uv run ruff check benchmarks/inference.py tests/test_inference.py
rtk proxy uv run mypy benchmarks/inference.py tests/test_inference.py
```

HTTP transport and process samplers are replaced in the tests. The suite checks
schedule/payload identity, cache evidence, failure denominators, charged errors,
strict numerics, real generated PNG dimensions, sampler scope, discovery,
output collision and content-free JSON/Markdown. It performs no real inference,
native actions, paid requests or server-process changes.
