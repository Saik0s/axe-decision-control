"""Benchmark proof uses HTTP/resource doubles, never a running inference server."""

from __future__ import annotations

import base64
import io
import json
from collections.abc import Callable
from pathlib import Path
from typing import NoReturn

import httpx
import pytest
from PIL import Image
from pydantic import JsonValue, TypeAdapter, ValidationError

from benchmarks import inference as bench
from benchmarks.resources import ProcessSampler, ResourceReport, ResourceSample

_OBJECT: TypeAdapter[dict[str, JsonValue]] = TypeAdapter(dict[str, JsonValue])


@pytest.fixture(autouse=True)
def synthetic_resources(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ProcessSampler, "start", lambda self: None)

    def stop(self: ProcessSampler) -> ResourceReport:
        return ResourceReport(pid=12345, samples=[ResourceSample(
            t_seconds=0.0, rss_kib=123456, cpu_percent=250.0)], peak_rss_kib=123456)

    monkeypatch.setattr(ProcessSampler, "stop", stop)


def _config(repeats: int = 5) -> bench.Config:
    return bench.Config(base_url="http://127.0.0.1:8093", model="Winnow-12B",
                        server_pid=12345, repeats=repeats)


def _body(request: httpx.Request) -> dict[str, JsonValue]:
    wire = _OBJECT.validate_json(request.content)
    questions = wire["questions"]
    options = wire["winnow"]
    assert isinstance(questions, dict) and isinstance(options, dict)
    reuse = options["reuse_prefix"]
    assert type(reuse) is bool
    return {
        "model": "Winnow-12B",
        "answers": {key: {"type": "noul", "noul": 0.75} for key in questions},
        "usage": {"input_tokens": 120 + 40 * len(questions), "output_tokens": 0, "cost": 0.01},
        "winnow": {
            "cache_hit": reuse, "prefix_reused_tokens": 120 if reuse else 0,
            "prefix_processed_tokens": 0 if reuse else 120,
            "question_count": len(questions), "unique_questions": len(questions),
            "prefix_tokens": 120, "suffix_tokens": 40 * len(questions),
            "image_tokens": 81 if options["images"] else 0,
            "native_ms": 20.0, "prefill_ms": 5.0, "request_prefill_ms": 2.0,
            "queue_ms": 0.5, "backend_allocated_bytes": 14658093056,
            "backend_budget_bytes": 55662788608, "context_capacity": 8192,
            "private_future_diagnostic": "numeric-canary-not-for-export",
        },
        "private_echo": "numeric-canary-not-for-export",
    }


def _transport(
    mutate: Callable[[dict[str, JsonValue], int], httpx.Response | None] | None = None,
    requests: list[httpx.Request] | None = None,
) -> httpx.MockTransport:
    attempt = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal attempt
        if requests is not None:
            requests.append(request)
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok", "private": "discovery-canary"})
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "Winnow-12B", "meta": {
                "n_ctx": 8192, "ftype": "Q8_0", "private": "discovery-canary"}}]})
        assert request.method == "POST" and request.url.path == "/v1/systemone"
        attempt += 1
        body = _body(request)
        replacement = mutate(body, attempt) if mutate is not None else None
        return replacement if replacement is not None else httpx.Response(200, json=body)

    return httpx.MockTransport(respond)


def test_six_bounded_workloads_distinct_questions_and_real_png_dimensions() -> None:
    assert [case.questions for case in bench.CASES] == [1, 8, 16, 32, 1, 4]
    sizes: list[int] = []
    for case in bench.CASES:
        request = bench.workload(case, False)
        state_bytes = len(json.dumps(request.state, separators=(",", ":")).encode())
        assert state_bytes <= bench.STATE_BYTE_LIMIT
        sizes.append(state_bytes)
        assert len({q.model_dump_json() for q in request.questions.values()}) == case.questions
        assert request == bench.workload(case, False)
        if request.images:
            with Image.open(io.BytesIO(base64.b64decode(request.images[0].split(",")[1]))) as image:
                assert image.size == (case.image_width, case.image_height)
    assert sizes[0] < sizes[1] < sizes[2]


def test_full_schedule_and_numeric_evidence_without_transformation_content() -> None:
    requests: list[httpx.Request] = []
    report = bench.run(_config(), _transport(requests=requests))
    assert len(report.samples) == 66
    assert report.samples[0].sample_id == 1 and report.samples[-1].sample_id == 66
    assert len(report.series) == 12 and len(report.cold_over_warm_wall_ratio) == 6
    assert all(s.regime_verified and s.valid_samples == 5 for s in report.series)
    posts = [request for request in requests if request.method == "POST"]
    assert [str(request.url) for request in requests[:2]] == [
        "http://127.0.0.1:8093/health", "http://127.0.0.1:8093/v1/models"]
    for index in range(6):
        rows = report.samples[index * 11:(index + 1) * 11]
        assert [s.stage for s in rows] == ["cold"] * 5 + ["setup"] + ["warm"] * 5
        assert [s.reuse_prefix for s in rows] == [False] * 5 + [True] * 6
        warm_bodies = [posts[index * 11 + i].content for i in range(5, 11)]
        assert len(set(warm_bodies)) == 1
        for sample in rows:
            assert sample.answers_valid and not sample.issues
            assert sample.native.unique_questions == sample.distinct_questions
            assert sample.call is not None and sample.call.succeeded
            assert sample.wire_usage.input_tokens == 120 + 40 * sample.submitted_questions
            assert sample.call.usage.prefill_ms == 7.0
            assert sample.native.prefill_ms == 5.0 and sample.native.request_prefill_ms == 2.0
            assert sample.native.backend_allocated_bytes == 14658093056
            assert sample.resources.scope == "whole_process"
            assert sample.resources.samples[0].cpu_percent == 250.0
    assert report.probes[1].models[0].n_ctx == 8192
    assert bench.Report.model_validate_json(report.model_dump_json()) == report
    for text in (report.model_dump_json(), bench.markdown(report)):
        assert "numeric-canary-not-for-export" not in text
        assert "discovery-canary" not in text
        assert "Synthetic control" not in text and "data:image" not in text
        assert '"answers"' not in text and '"state"' not in text
    rendered = bench.markdown(report)
    assert "whole-process" in rendered and "backend/device" in rendered
    assert "not model startup" in rendered and "not energy" in rendered
    assert report.series[0].latency["prefill_ms"].median == 5.0
    assert report.series[0].latency["request_prefill_ms"].median == 2.0
    assert report.series[0].latency["provider_prefill_ms"].median == 7.0


@pytest.mark.parametrize("missing", ["all", "cache_hit", "prefix_reused_tokens"])
def test_missing_diagnostics_never_count_as_verified_warm(missing: str) -> None:
    def mutate(body: dict[str, JsonValue], attempt: int) -> None:
        native = body["winnow"]
        assert isinstance(native, dict)
        if native["cache_hit"]:
            if missing == "all":
                body.pop("winnow")
            else:
                native.pop(missing)

    report = bench.run(_config(), _transport(mutate))
    warm = [s for s in report.series if s.stage == "warm"]
    assert all(s.valid_samples == 0 and s.failures == 5 and not s.regime_verified for s in warm)
    assert not report.cold_over_warm_wall_ratio
    assert all(s.answers_valid for s in report.samples)


def test_cold_prefix_reuse_invalidates_claim_and_keeps_failure_denominator() -> None:
    def mutate(body: dict[str, JsonValue], attempt: int) -> None:
        if attempt == 1:
            native = body["winnow"]
            assert isinstance(native, dict)
            native["prefix_reused_tokens"] = 9

    report = bench.run(_config(), _transport(mutate))
    cold = report.series[0]
    assert (cold.attempts, cold.valid_samples, cold.failures) == (5, 4, 1)
    assert not cold.regime_verified and "1" not in report.cold_over_warm_wall_ratio
    assert report.samples[0].issues == ["cache_regime_unverified"]
    report.samples[0].wall_ms = 1_000_000.0
    cold = bench.summarize(report.samples, report.cases)[0]
    assert cold.latency["wall_ms"].n == 4 and cold.latency["wall_ms"].maximum < 1_000_000.0


@pytest.mark.parametrize("failure", ["http", "typed_schema", "answer_ids"])
def test_failed_attempts_retain_numeric_cost_tokens_and_errors(failure: str) -> None:
    def mutate(body: dict[str, JsonValue], attempt: int) -> httpx.Response | None:
        if attempt != 1:
            return None
        if failure == "http":
            return httpx.Response(503, json={
                "error": "http-canary", "usage": body["usage"], "winnow": body["winnow"]})
        answers = body["answers"]
        assert isinstance(answers, dict)
        if failure == "typed_schema":
            answers["q0"] = {"type": "noul", "noul": 3.0}
        else:
            body["answers"] = {"wrong-id": {"type": "noul", "noul": 0.5}}
        return None

    report = bench.run(_config(), _transport(mutate))
    failed = report.samples[0]
    assert not failed.answers_valid and failed.issues
    assert failed.wall_ms > 0 and failed.call is not None and not failed.call.succeeded
    assert failed.call.usage.request_ms > 0
    assert failed.wire_usage.cost == 0.01 and failed.wire_usage.input_tokens == 160
    assert failed.native.native_ms == 20.0
    assert report.series[0].failures == 1 and report.series[0].latency["wall_ms"].n == 4
    assert "http-canary" not in report.model_dump_json()


def test_unknown_cost_missing_images_and_unique_mismatch_are_explicit() -> None:
    def mutate(body: dict[str, JsonValue], attempt: int) -> None:
        usage, native = body["usage"], body["winnow"]
        assert isinstance(usage, dict) and isinstance(native, dict)
        usage.pop("cost")
        native.pop("image_tokens")
        if attempt == 1:
            native["unique_questions"] = 0

    report = bench.run(_config(), _transport(mutate))
    assert all(s.wire_usage.cost is None for s in report.samples)
    assert "unique_question_count_mismatch" in report.samples[0].issues
    images = [s for s in report.samples if s.case_id in {5, 6}]
    assert all("image_tokens_unavailable" in s.issues for s in images)
    assert all(s.native.image_tokens is None for s in images)


def test_small_n_and_failed_setup_preclude_ratios() -> None:
    report = bench.run(_config(repeats=2), _transport())
    assert all(s.valid_samples == 2 and not s.regime_verified for s in report.series)
    assert not report.cold_over_warm_wall_ratio

    def mutate(body: dict[str, JsonValue], attempt: int) -> httpx.Response | None:
        return httpx.Response(500, text="setup-canary") if attempt == 6 else None

    failed_setup = bench.run(_config(), _transport(mutate))
    assert failed_setup.series[1].valid_samples == 5
    assert not failed_setup.series[1].regime_verified
    assert "1" not in failed_setup.cold_over_warm_wall_ratio


def test_nearest_rank_p95_is_numeric_maximum_for_five_samples() -> None:
    result = bench.stats([1.0, 100.0, 4.0, 2.0, 3.0])
    assert (result.n, result.median, result.minimum, result.maximum, result.sample_p95) == (
        5, 3.0, 1.0, 100.0, 100.0)


@pytest.mark.parametrize("value", [-1.0, float("nan"), float("inf"), True, "12", 10**309])
def test_strict_numerics_reject_invalid_samples_and_do_not_fabricate_zero(value: JsonValue) -> None:
    with pytest.raises(ValidationError):
        bench.WireUsage.model_validate({"cost": value})
    fields = bench.numeric_fields({"cost": value}, {"cost"})
    assert not fields
    assert bench.WireUsage.model_validate(fields).cost is None


def test_overflowing_cost_preserves_other_metrics_and_charged_attempt_record() -> None:
    def mutate(body: dict[str, JsonValue], attempt: int) -> None:
        if attempt == 1:
            usage = body["usage"]
            assert isinstance(usage, dict)
            usage["cost"] = 10**309

    report = bench.run(_config(), _transport(mutate))
    failed = report.samples[0]
    assert not failed.answers_valid and "invalid_numeric_usage" in failed.issues
    assert failed.wire_usage.cost is None and failed.wire_usage.input_tokens == 160
    assert failed.native.native_ms == 20.0 and failed.call is not None
    assert len(report.samples) == 66 and report.series[0].failures == 1


def test_transport_failure_retains_real_duration_and_no_stale_metrics() -> None:
    attempt = 0
    healthy = _transport()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempt
        if request.method == "POST":
            attempt += 1
            if attempt == 2:
                raise httpx.ConnectError("transport-private-canary", request=request)
        return healthy.handle_request(request)

    report = bench.run(_config(), httpx.MockTransport(handler))
    failed = report.samples[1]
    assert failed.issues == ["transport_error"] and failed.http_status is None
    assert not failed.answers_valid and failed.wall_ms > 0
    assert failed.call is not None and failed.call.usage.request_ms > 0
    assert failed.wire_usage.input_tokens is None and failed.wire_usage.cost is None
    assert failed.native.prefix_processed_tokens is None
    assert "transport-private-canary" not in report.model_dump_json()


def test_sampler_failure_does_not_invent_samples_or_hide_latency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(self: ProcessSampler) -> NoReturn:
        raise RuntimeError("ps-canary")

    monkeypatch.setattr(ProcessSampler, "start", fail)
    report = bench.run(_config(repeats=3), _transport())
    assert all(s.regime_verified for s in report.series)
    assert all(s.resources.errors == ["sampler_start_failed"] for s in report.samples)
    assert all(not s.resources.samples and s.resources.peak_rss_kib is None for s in report.samples)
    assert "ps-canary" not in report.model_dump_json()


@pytest.mark.parametrize("route", ["/health", "/v1/models"])
def test_discovery_failure_saves_no_fabricated_attempts(route: str) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == route:
            return httpx.Response(503, text="discovery-failure-canary")
        return _transport().handle_request(request)

    report = bench.run(_config(), httpx.MockTransport(handler))
    assert len(requests) == 2 and all(request.method == "GET" for request in requests)
    assert not report.samples and not report.series and not report.cold_over_warm_wall_ratio
    assert "discovery-failure-canary" not in report.model_dump_json()


def test_output_collision_precedes_network_and_preserves_existing_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "existing"
    output.mkdir()
    (output / "report.md").write_text("keep-existing", encoding="utf-8")

    def deny(config: bench.Config) -> NoReturn:
        raise AssertionError("Output collision reached inference")

    monkeypatch.setattr(bench, "run", deny)
    with pytest.raises(SystemExit) as error:
        bench.main(["--base-url", "http://127.0.0.1:8093", "--model", "Winnow-12B",
                    "--server-pid", "12345", "--output", str(output)])
    assert error.value.code == 2
    assert (output / "report.md").read_text() == "keep-existing"


def test_cli_exports_strict_numeric_json_and_markdown(tmp_path: Path,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    actual_run = bench.run

    def mocked_run(config: bench.Config) -> bench.Report:
        return actual_run(config, _transport())

    monkeypatch.setattr(bench, "run", mocked_run)
    output = tmp_path / "numeric-proof"
    assert bench.main(["--base-url", "http://127.0.0.1:8093", "--model", "Winnow-12B",
                       "--server-pid", "12345", "--output", str(output)]) == 0
    saved = bench.Report.model_validate_json((output / "results.json").read_bytes())
    assert len(saved.samples) == 66 and saved.samples[0].wire_usage.input_tokens == 160
    assert (output / "report.md").read_text() == bench.markdown(saved)


@pytest.mark.parametrize("url", ["https://example.com", "http://user:secret@localhost:8093",
                               "http://127.0.0.1:8093/private", "http://127.0.0.1:8093?key=x"])
def test_nonlocal_or_credentialed_targets_are_rejected_before_requests(url: str) -> None:
    requests: list[httpx.Request] = []
    config = _config().model_copy(update={"base_url": url})
    with pytest.raises(ValueError, match="loopback"):
        bench.run(config, _transport(requests=requests))
    assert not requests


def test_operator_metadata_is_strict_and_never_claimed_as_discovery() -> None:
    launch = bench.LaunchMetadata(context_capacity=8192, backend="Metal", device="Apple M2 Ultra",
                                 quantization="Q8_0", kv_cache="F16", projector_loaded=True)
    with pytest.raises(ValidationError):
        bench.LaunchMetadata.model_validate({"weights_path": "/private/weights"})
    config = _config().model_copy(update={"launch": launch})
    report = bench.run(config, _transport())
    assert report.config.launch == launch
    assert report.host.logical_cpus is not None and report.host.logical_cpus > 0
    assert report.host.python and "pydantic" in report.host.packages
