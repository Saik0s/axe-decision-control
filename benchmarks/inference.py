"""Synthetic, sequential Winnow prefix-cache benchmark. No simulator or server control."""

from __future__ import annotations

import argparse
import base64
import io
import json
import math
import os
import platform
import statistics
import subprocess
import time
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Annotated, Literal

import httpx
from PIL import Image, ImageDraw
from pydantic import AliasPath, ConfigDict, Field, JsonValue, TypeAdapter, ValidationError

from axe_control.decisions import (
    Count,
    DecisionRequest,
    ModelCall,
    Nonnegative,
    NoulQuestion,
    ProviderError,
    StrictModel,
)
from axe_control.providers.winnow import WinnowProvider

from .resources import ProcessSampler, ResourceReport

Positive = Annotated[int, Field(gt=0)]
Label = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9 ._/()+-]{0,127}$")]
Commit = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
Stage = Literal["cold", "setup", "warm"]
MIN_SAMPLES = 3
STATE_BYTE_LIMIT = 7000
_OBJECT: TypeAdapter[dict[str, JsonValue]] = TypeAdapter(dict[str, JsonValue])


class LaunchMetadata(StrictModel):
    """Optional operator declarations, never inferred from a PID or documentation."""

    context_capacity: Positive | None = None
    backend: Label | None = None
    device: Label | None = None
    quantization: Label | None = None
    kv_cache: Label | None = None
    projector_loaded: bool | None = None
    parallel: Positive | None = None
    winnow_commit: Commit | None = None
    llama_cpp_commit: Commit | None = None


class Config(StrictModel):
    base_url: str
    model: Label
    server_pid: Positive
    repeats: Annotated[int, Field(ge=1, le=100)] = 5
    timeout_seconds: Annotated[float, Field(gt=0, allow_inf_nan=False)] = 180.0
    launch: LaunchMetadata = Field(default_factory=LaunchMetadata)


class Case(StrictModel):
    case_id: Positive
    name: Label
    widgets: Positive
    questions: Positive
    image_width: Count = 0
    image_height: Count = 0


CASES = (
    Case(case_id=1, name="text-small-1q", widgets=4, questions=1),
    Case(case_id=2, name="text-medium-8q", widgets=24, questions=8),
    Case(case_id=3, name="text-large-16q", widgets=64, questions=16),
    Case(case_id=4, name="text-many-32q", widgets=24, questions=32),
    Case(case_id=5, name="image-256-1q", widgets=4, questions=1,
         image_width=256, image_height=256),
    Case(case_id=6, name="image-phone-portrait-4q", widgets=12, questions=4,
         image_width=402, image_height=874),
)


class WireUsage(StrictModel):
    input_tokens: Count | None = None
    output_tokens: Count | None = None
    cost: Nonnegative | None = None


class NativeMetrics(StrictModel):
    cache_hit: bool | None = None
    image_tokens: Count | None = None
    prefix_tokens: Count | None = None
    suffix_tokens: Count | None = None
    prefix_reused_tokens: Count | None = None
    prefix_processed_tokens: Count | None = None
    request_prefix_reused_tokens: Count | None = None
    request_prefix_processed_tokens: Count | None = None
    unique_questions: Count | None = None
    question_count: Count | None = None
    leaf_processed_tokens: Count | None = None
    context_capacity: Count | None = None
    context_evictions: Count | None = None
    backend_allocated_bytes: Count | None = None
    backend_budget_bytes: Count | None = None
    native_ms: Nonnegative | None = None
    prefill_ms: Nonnegative | None = None
    request_prefill_ms: Nonnegative | None = None
    decode_ms: Nonnegative | None = None
    queue_ms: Nonnegative | None = None


def numeric_fields(raw: JsonValue, names: set[str]) -> dict[str, JsonValue]:
    if not isinstance(raw, dict):
        return {}
    result: dict[str, JsonValue] = {}
    for key in names:
        value = raw.get(key)
        if value is None:
            continue
        if key == "cache_hit":
            if type(value) is bool:
                result[key] = value
        elif key.endswith("_ms") or key == "cost":
            if type(value) in {int, float} and isinstance(value, (int, float)):
                try:
                    if math.isfinite(value) and value >= 0:
                        result[key] = value
                except OverflowError:
                    pass
        elif type(value) is int and isinstance(value, int) and value >= 0:
            result[key] = value
    return result


class Capture(httpx.BaseTransport):
    """Keep allowlisted numeric evidence even when answer validation or HTTP fails."""

    def __init__(self, inner: httpx.BaseTransport) -> None:
        self.inner = inner
        self.reset()

    def reset(self) -> None:
        self.status: int | None = None
        self.usage = WireUsage()
        self.native = NativeMetrics()
        self.issues: list[str] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self.inner.handle_request(request)
        self.status = response.status_code
        try:
            body = _OBJECT.validate_json(response.read())
        except ValidationError:
            return response
        usage = numeric_fields(body.get("usage"), set(WireUsage.model_fields))
        native = numeric_fields(body.get("winnow"), set(NativeMetrics.model_fields))
        for key, fields, names in (("usage", usage, set(WireUsage.model_fields)),
                                   ("winnow", native, set(NativeMetrics.model_fields))):
            raw = body.get(key)
            if isinstance(raw, dict) and any(
                name in raw and raw[name] is not None and name not in fields for name in names
            ):
                self.issues.append("invalid_numeric_" + key)
        self.usage = WireUsage.model_validate(usage)
        self.native = NativeMetrics.model_validate(native)
        return response

    def close(self) -> None:
        self.inner.close()


class Sample(StrictModel):
    sample_id: Positive
    case_id: Positive
    stage: Stage
    repetition: Count
    reuse_prefix: bool
    state_bytes: Count
    submitted_questions: Count
    distinct_questions: Count
    wall_ms: Nonnegative
    answers_valid: bool
    http_status: Count | None
    call: ModelCall | None
    wire_usage: WireUsage
    native: NativeMetrics
    issues: list[str]
    resources: ResourceReport


class Stats(StrictModel):
    n: Positive
    median: Nonnegative
    minimum: Nonnegative
    maximum: Nonnegative
    sample_p95: Nonnegative


class Series(StrictModel):
    case_id: Positive
    stage: Literal["cold", "warm"]
    attempts: Count
    valid_samples: Count
    failures: Count
    regime_verified: bool
    latency: dict[str, Stats]


class Host(StrictModel):
    platform: str
    architecture: str
    cpu_model: str | None
    logical_cpus: Count | None
    physical_memory_bytes: Count | None
    python: str
    packages: dict[str, str | None]


class ModelEntry(StrictModel):
    model_config = ConfigDict(strict=True, extra="ignore", populate_by_name=True)
    id: Label
    n_ctx: Count | None = Field(default=None, validation_alias=AliasPath("meta", "n_ctx"))
    n_params: Count | None = Field(default=None, validation_alias=AliasPath("meta", "n_params"))
    size: Count | None = Field(default=None, validation_alias=AliasPath("meta", "size"))
    ftype: Label | None = Field(default=None, validation_alias=AliasPath("meta", "ftype"))


class Probe(StrictModel):
    route: Literal["/health", "/v1/models"]
    http_status: Count | None = None
    verified: bool = False
    health_status: Literal["ok"] | None = None
    models: list[ModelEntry] = Field(default_factory=list)
    issue: str | None = None


class Report(StrictModel):
    schema_version: Literal[1] = 1
    created_utc: str
    config: Config
    host: Host
    probes: list[Probe]
    cases: list[Case]
    samples: list[Sample] = Field(default_factory=list)
    series: list[Series] = Field(default_factory=list)
    cold_over_warm_wall_ratio: dict[str, Nonnegative] = Field(default_factory=dict)


def workload(case: Case, reuse_prefix: bool) -> DecisionRequest:
    widgets: list[JsonValue] = [
        {"id": index, "label": f"Synthetic control {index}", "enabled": index % 3 != 0,
         "value": index % 5, "section": index // 4}
        for index in range(case.widgets)
    ]
    state: JsonValue = {"screen": "Synthetic panel", "revision": 1, "controls": widgets}
    if len(json.dumps(state, separators=(",", ":")).encode()) > STATE_BYTE_LIMIT:
        raise ValueError("Synthetic state exceeds the byte bound")
    images: tuple[str, ...] = ()
    if case.image_width:
        image = Image.new("RGB", (case.image_width, case.image_height), "#e7edf5")
        draw = ImageDraw.Draw(image)
        for index in range(4):
            top = 24 + index * (case.image_height // 5)
            draw.rectangle((20, top, case.image_width - 20, top + 30), fill="#3058a0")
            draw.text((26, top + 8), f"Synthetic item {index}", fill="white")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        images = ("data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode(),)
    return DecisionRequest(state=state, images=images, reuse_prefix=reuse_prefix, questions={
        f"q{index}": NoulQuestion(instructions=(
            f"Is synthetic control {index % case.widgets} enabled? "
            f"Evaluate check {index} using the supplied panel and image if present."
        )) for index in range(case.questions)
    })


def cache_issues(stage: Stage, native: NativeMetrics) -> list[str]:
    verified = (stage == "setup"
                or (stage == "cold" and native.prefix_reused_tokens == 0
                    and (native.prefix_processed_tokens or 0) > 0)
                or (stage == "warm" and native.cache_hit is True
                    and (native.prefix_reused_tokens or 0) > 0))
    return [] if verified else ["cache_regime_unverified"]


def measure(provider: WinnowProvider, capture: Capture, request: DecisionRequest,
            case: Case, stage: Stage, repetition: int, sample_id: int, pid: int) -> Sample:
    capture.reset()
    sampler = ProcessSampler(pid)
    resources = ResourceReport(pid=pid, errors=["sampler_start_failed"])
    sampling = False
    try:
        sampler.start()
        sampling = True
    except RuntimeError:
        pass
    before = len(provider.calls)
    started = time.perf_counter()
    issues: list[str] = []
    valid = False
    try:
        provider.decide(request)
        valid = True
    except ProviderError as error:
        issues.append("http_error" if capture.status is not None
                      and not 200 <= capture.status < 300
                      else "transport_error" if str(error) == "Provider HTTP transport failed"
                      else "schema_error" if capture.status is not None
                      else "provider_error")
    finally:
        wall_ms = (time.perf_counter() - started) * 1000
        if sampling:
            resources = sampler.stop()
    calls = provider.calls[before:]
    call = calls[0] if len(calls) == 1 else None
    issues.extend(capture.issues)
    if call is None:
        issues.append("attempt_telemetry_unavailable")
    if valid:
        issues.extend(cache_issues(stage, capture.native))
        if capture.usage.input_tokens is None:
            issues.append("input_tokens_unavailable")
        if request.images and capture.native.image_tokens is None:
            issues.append("image_tokens_unavailable")
        if (capture.native.unique_questions is not None
                and capture.native.unique_questions != len(request.questions)):
            issues.append("unique_question_count_mismatch")
    return Sample(sample_id=sample_id, case_id=case.case_id, stage=stage,
                  repetition=repetition, reuse_prefix=request.reuse_prefix,
                  state_bytes=len(json.dumps(request.state, separators=(",", ":")).encode()),
                  submitted_questions=len(request.questions),
                  distinct_questions=len({q.model_dump_json() for q in request.questions.values()}),
                  wall_ms=wall_ms, answers_valid=valid, http_status=capture.status, call=call,
                  wire_usage=capture.usage, native=capture.native,
                  issues=issues, resources=resources)


def stats(values: list[float]) -> Stats:
    ordered = sorted(values)
    return Stats(n=len(values), median=float(statistics.median(values)), minimum=ordered[0],
                 maximum=ordered[-1], sample_p95=ordered[math.ceil(0.95 * len(values)) - 1])


def summarize(samples: list[Sample], cases: list[Case]) -> list[Series]:
    result: list[Series] = []
    for case in cases:
        setup_ok = any(s.case_id == case.case_id and s.stage == "setup"
                       and s.answers_valid and not s.issues for s in samples)
        for stage in ("cold", "warm"):
            rows = [s for s in samples if s.case_id == case.case_id and s.stage == stage]
            valid = [s for s in rows if s.answers_valid and not s.issues]
            metrics: dict[str, list[float]] = {"wall_ms": [s.wall_ms for s in valid]}
            for sample in valid:
                timings: dict[str, float | None] = {
                    "request_ms": sample.call.usage.request_ms if sample.call else None,
                    "native_ms": sample.native.native_ms, "prefill_ms": sample.native.prefill_ms,
                    "request_prefill_ms": sample.native.request_prefill_ms,
                    "provider_prefill_ms": sample.call.usage.prefill_ms if sample.call else None,
                    "queue_ms": sample.native.queue_ms,
                }
                for key, value in timings.items():
                    if value is not None:
                        metrics.setdefault(key, []).append(value)
            result.append(Series(case_id=case.case_id, stage=stage, attempts=len(rows),
                                 valid_samples=len(valid), failures=len(rows) - len(valid),
                                 regime_verified=(len(valid) >= MIN_SAMPLES
                                                  and len(valid) == len(rows)
                                                  and (stage == "cold" or setup_ok)),
                                 latency={k: stats(v) for k, v in metrics.items() if v}))
    return result


def host_metadata() -> Host:
    cpu, memory = platform.processor() or None, None
    if platform.system() == "Darwin":
        for key in ("machdep.cpu.brand_string", "hw.memsize"):
            try:
                text = subprocess.run(["sysctl", "-n", key], capture_output=True, text=True,
                                      check=True, timeout=2).stdout.strip()
                if key == "hw.memsize":
                    memory = int(text)
                else:
                    cpu = text
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
    elif hasattr(os, "sysconf"):
        try:
            memory = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
        except (OSError, ValueError):
            pass
    packages: dict[str, str | None] = {}
    for name in ("axe-decision-control", "httpx", "pydantic", "Pillow"):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = None
    return Host(platform=platform.platform(), architecture=platform.machine(), cpu_model=cpu,
                logical_cpus=os.cpu_count(), physical_memory_bytes=memory,
                python=platform.python_version(), packages=packages)


def probe(config: Config, transport: httpx.BaseTransport | None) -> list[Probe]:
    probes: list[Probe] = []
    with httpx.Client(transport=transport, timeout=config.timeout_seconds, trust_env=False,
                      follow_redirects=False) as client:
        for route in ("/health", "/v1/models"):
            row = Probe(route=route)
            try:
                response = client.get(config.base_url.rstrip("/") + route)
                row.http_status = response.status_code
                response.raise_for_status()
                body = _OBJECT.validate_json(response.content)
                if route == "/health":
                    row.verified = body.get("status") == "ok"
                    row.health_status = "ok" if row.verified else None
                else:
                    row.models = TypeAdapter(list[ModelEntry]).validate_python(body.get("data"))
                    row.verified = any(model.id == config.model for model in row.models)
                if not row.verified:
                    row.issue = "discovery_identity_unverified"
            except (httpx.HTTPError, ValidationError):
                row.issue = "discovery_failed"
            probes.append(row)
    return probes


def run(config: Config, transport: httpx.BaseTransport | None = None) -> Report:
    url = httpx.URL(config.base_url)
    if (url.scheme not in {"http", "https"} or url.host not in {"localhost", "127.0.0.1", "::1"}
            or url.userinfo or url.query or url.fragment or url.path not in {"", "/"}):
        raise ValueError("Benchmark requires a loopback base URL without credentials or path")
    report = Report(created_utc=datetime.now(UTC).isoformat(), config=config,
                    host=host_metadata(), probes=probe(config, transport), cases=list(CASES))
    if not all(row.verified for row in report.probes):
        return report
    capture = Capture(transport or httpx.HTTPTransport())
    with WinnowProvider(model=config.model, base_url=config.base_url,
                        timeout=config.timeout_seconds, transport=capture) as provider:
        for case in CASES:
            schedule: tuple[tuple[Stage, int], ...] = (
                ("cold", config.repeats), ("setup", 1), ("warm", config.repeats))
            for stage, count in schedule:
                request = workload(case, reuse_prefix=stage != "cold")
                for repetition in range(count):
                    report.samples.append(measure(provider, capture, request, case, stage,
                                                  repetition, len(report.samples) + 1,
                                                  config.server_pid))
    report.series = summarize(report.samples, report.cases)
    for case in report.cases:
        cold, warm = [s for s in report.series if s.case_id == case.case_id]
        if cold.regime_verified and warm.regime_verified and warm.latency["wall_ms"].median > 0:
            report.cold_over_warm_wall_ratio[str(case.case_id)] = (
                cold.latency["wall_ms"].median / warm.latency["wall_ms"].median)
    return report


def markdown(report: Report) -> str:
    lines = ["# Local inference performance", "", f"Created: {report.created_utc}", "",
             f"Host: {report.host.cpu_model}; RAM bytes: {report.host.physical_memory_bytes}.",
             f"Python: {report.host.python}; platform: {report.host.platform}.",
             f"Architecture: {report.host.architecture}; logical CPUs: {report.host.logical_cpus}.",
             f"Packages: {json.dumps(report.host.packages, sort_keys=True)}.",
             f"Model: {report.config.model}; PID: {report.config.server_pid}.",
             f"Discovery: {json.dumps([p.model_dump() for p in report.probes], sort_keys=True)}.",
             "Operator-declared launch: "
             f"{report.config.launch.model_dump_json(exclude_none=True)}.",
             "",
             "Cold means prefix reuse disabled, not model startup or filesystem-cache cold.",
             "Warm requires cache_hit=true and prefix_reused_tokens>0 for every included sample.",
             "Ratios require every attempt valid and at least 3 samples per regime, plus setup.",
             "p95 is nearest-rank sample p95; at n=5 it is the maximum, not tail proof.",
             "RSS/CPU are whole-process observations in request windows, not request allocations.",
             "Backend allocation/budget describes the backend/device, not a per-request peak.",
             "CPU is ps percent, not energy. No calibrated quality or capacity claim.", ""]
    for case in report.cases:
        rows = [s for s in report.samples if s.case_id == case.case_id]
        lines.extend([f"## {case.name}", "", f"Questions: {case.questions}; "
                      f"image dimensions: {case.image_width} x {case.image_height}."])
        measurements: dict[str, list[int | float | None]] = {
            "state_bytes": [s.state_bytes for s in rows],
            "input_tokens": [s.wire_usage.input_tokens for s in rows],
            "image_tokens": [s.native.image_tokens for s in rows],
            "unique_questions": [s.native.unique_questions for s in rows],
            "backend_allocated_bytes": [s.native.backend_allocated_bytes for s in rows],
            "backend_budget_bytes": [s.native.backend_budget_bytes for s in rows],
        }
        for key, observed in measurements.items():
            values = [v for v in observed if v is not None]
            text = f"{min(values)} to {max(values)} (n={len(values)})" if values else "unavailable"
            lines.append(f"Observed {key}, all attempts including setup/errors: {text}.")
        for sample in rows:
            if sample.issues or sample.resources.errors:
                lines.append(f"Sample {sample.sample_id} ({sample.stage}), "
                             f"HTTP {sample.http_status}: "
                             f"{sample.issues + sample.resources.errors}.")
        for series in [s for s in report.series if s.case_id == case.case_id]:
            lines.append(f"{series.stage}: {series.valid_samples}/{series.attempts} valid; "
                         f"failures {series.failures}; regime verified {series.regime_verified}.")
            for name, value in series.latency.items():
                lines.append(f"- {name}: n={value.n}, median {value.median:.3f}, "
                             f"min {value.minimum:.3f}, max {value.maximum:.3f}, "
                             f"sample p95 {value.sample_p95:.3f}")
        ratio = report.cold_over_warm_wall_ratio.get(str(case.case_id))
        ratio_text = str(ratio) if ratio is not None else "unavailable"
        lines.extend([f"Cold/warm wall median ratio: {ratio_text}.",
                      ""])
    costs = [s.wire_usage.cost for s in report.samples if s.wire_usage.cost is not None]
    resources = [r for s in report.samples for r in s.resources.samples]
    lines.extend([f"All-attempt reported cost USD: {sum(costs) if costs else 'unavailable'}; "
                  f"unpriced attempts: {len(report.samples) - len(costs)}.",
                  f"Whole-process RSS observed maximum KiB: "
                  f"{max((r.rss_kib for r in resources), default=None)}; CPU observed maximum "
                  f"ps percent: {max((r.cpu_percent for r in resources), default=None)}; "
                  f"resource observations: {len(resources)}.", ""])
    lines.extend(["Setup attempts are separate and excluded from latency summaries. All attempts,",
                  "numeric token/native/cost evidence, errors and RSS/CPU are in results.json.",
                  "Missing metrics and unreported costs remain null, never inferred as zero.", ""])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--server-pid", required=True, type=int)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--launch-metadata", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        launch = (LaunchMetadata.model_validate_json(args.launch_metadata.read_bytes())
                  if args.launch_metadata else LaunchMetadata())
        config = Config(base_url=args.base_url, model=args.model, server_pid=args.server_pid,
                        repeats=args.repeats, timeout_seconds=args.timeout_seconds, launch=launch)
        args.output.mkdir(parents=True, exist_ok=False)
        report = run(config)
        (args.output / "results.json").write_text(report.model_dump_json(indent=2),
                                                encoding="utf-8")
        (args.output / "report.md").write_text(markdown(report), encoding="utf-8")
    except (OSError, ValueError, httpx.InvalidURL):
        parser.exit(2, "Benchmark configuration, output collision, or output write failed.\n")
    return 0 if report.series and all(s.regime_verified for s in report.series) else 2


if __name__ == "__main__":
    raise SystemExit(main())
