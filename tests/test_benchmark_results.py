"""Synthetic benchmark contracts and orchestration, with no native or API execution."""

from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path
from typing import Literal, NoReturn

import pytest
from PIL import Image
from pydantic import JsonValue, TypeAdapter, ValidationError

from axe_control.decisions import ModelCall, ProviderIdentity, ProviderUsage
from axe_control.models import Mode, RunReport, ScreenSize
from axe_control.native import AXeTransport
from benchmarks import run
from benchmarks.resources import ProcessSampler
from benchmarks.summarize import (
    Episode,
    Expected,
    Initial,
    Oracle,
    Proof,
    ProviderConfig,
    Scenario,
    SyntheticTree,
    aggregate,
    evaluate,
    report_issues,
    sanitize_tree,
    summarize,
)

Status = Literal["completed", "blocked", "budget_exhausted", "cancelled", "failed"]
_OBJECT: TypeAdapter[dict[str, JsonValue]] = TypeAdapter(dict[str, JsonValue])
_SCREEN = ScreenSize(width=402.0, height=874.0)
_UDID = "11111111-2222-3333-4444-555555555555"


def _scenario(identifier: str = "alpha", *, quiet: bool = True) -> Scenario:
    return Scenario(
        id=identifier, goal="Start the requested synthetic session.",
        allowed_texts=["Synthetic session", "Alternate session"],
        initial=Initial(seed=7, duration=10, quiet=False, prefill="Draft", scroll=True),
        expected=Expected(name="Synthetic session", duration=25, quiet=quiet, phase="running"),
    )


def _config(mode: Mode = "tree") -> ProviderConfig:
    return ProviderConfig(provider="winnow", model="synthetic-model", mode=mode,
                          base_url="http://127.0.0.1:8093")


def _oracle(scenario: Scenario, seed: int) -> Oracle:
    expected = scenario.expected
    return Oracle(phase=expected.phase, name=expected.name, duration=expected.duration,
                  quiet=expected.quiet, seed=seed, screen_width=402.0, screen_height=874.0)


def _tree(scenario: Scenario) -> SyntheticTree:
    return SyntheticTree(labels=["FocusBench", "Session started", scenario.expected.name,
                                f"{scenario.expected.duration} minutes",
                                f"Quiet mode {'on' if scenario.expected.quiet else 'off'}"])


def _report(config: ProviderConfig, status: Status = "completed", *,
            unpriced: bool = False) -> RunReport:
    identity = ProviderIdentity(name=config.provider, requested_model=config.model,
                                endpoint=config.base_url + "/v1/systemone", local=True)
    generative_identity = identity.model_copy(
        update={"endpoint": config.base_url + "/v1/chat/completions"})
    cost = None if unpriced else 0.02
    return RunReport(
        mode=config.mode, status=status, reason="synthetic", steps=3, native_commands=8,
        native_mutations=3, native_failures=1, decision_requests=1, generative_requests=1,
        elapsed_seconds=6.0, model_seconds=3.0, reported_cost_usd=cost,
        unpriced_requests=2 if unpriced else 1,
        identity=generative_identity if config.mode == "direct" else identity, events=[], calls=[
            ModelCall(kind="decision", succeeded=True, identity=identity,
                      usage=ProviderUsage(request_ms=1000.0, reported_cost_usd=cost)),
            ModelCall(kind="generative", succeeded=status == "completed",
                      identity=generative_identity,
                      usage=ProviderUsage(request_ms=2000.0)),
        ],
    )


def _episode(scenario: Scenario | None = None, repetition: int = 0, *,
             mode: Mode = "tree", status: Status = "completed") -> Episode:
    scenario = scenario or _scenario()
    seed = scenario.initial.seed + 1009 * repetition
    config = _config(mode)
    return Episode(
        scenario=scenario, repetition=repetition, seed=seed, screen=_SCREEN,
        provider_config=config, report=_report(config, status),
        exit_code=0 if status == "completed" else 2,
        evaluation=evaluate(scenario, seed, _SCREEN, _oracle(scenario, seed), _tree(scenario)),
        setup_failures=[], proof=Proof(screenshot="final.png", tree="final-tree.json"),
    )


def _changed_report(report: RunReport, changes: dict[str, JsonValue]) -> RunReport:
    payload = _OBJECT.validate_json(report.model_dump_json())
    payload.update(changes)
    return RunReport.model_validate_json(json.dumps(payload))


def _deny_process(*arguments: object, **options: object) -> NoReturn:
    pytest.fail("Unexpected process or native execution in a pure benchmark test")


@pytest.fixture(autouse=True)
def _no_processes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", _deny_process)
    monkeypatch.setattr(subprocess, "Popen", _deny_process)


def test_scenario_strata_keep_failures_and_wilson_95_bounds() -> None:
    rows = [_episode(_scenario("alpha"), index) for index in range(3)]
    rows += [_episode(_scenario("beta"), index, status="failed") for index in range(3)]
    strata = aggregate(rows)
    assert [stratum.scenario for stratum in strata] == ["alpha", "beta"]
    good, bad = (stratum.counts for stratum in strata)
    assert (good.episodes, good.successes, good.failures) == (3, 3, 0)
    assert (bad.episodes, bad.successes, bad.failures) == (3, 0, 3)
    assert good.success_interval_95.low == pytest.approx(0.4385, abs=0.00005)
    assert good.success_interval_95.high == pytest.approx(1.0)
    assert bad.success_interval_95.low == pytest.approx(0.0, abs=1e-12)
    assert bad.success_interval_95.high == pytest.approx(0.5615, abs=0.00005)


def test_matrix_cells_and_geometry_are_never_pooled() -> None:
    rows = [_episode(mode="tree"), _episode(mode="direct"), _episode(mode="grid")]
    changed = _episode()
    changed.provider_config.model = "other-model"
    changed.report = _report(changed.provider_config)
    geometry = _episode()
    geometry.screen = ScreenSize(width=403.0, height=874.0)
    strata = aggregate([*rows, changed, geometry])
    assert len(strata) == 5
    assert sum(stratum.counts.successes for stratum in strata) == 4
    assert all(stratum.counts.episodes == 1 for stratum in strata)


def test_failed_and_missing_runs_preserve_time_cost_and_native_counts() -> None:
    missing = _episode(repetition=2)
    missing.report = None
    missing.exit_code = None
    missing.setup_failures = ["initial_geometry_mismatch"]
    counts = aggregate([_episode(), _episode(repetition=1, status="failed"), missing])[0].counts
    assert (counts.episodes, counts.successes, counts.failures) == (3, 1, 2)
    assert counts.statuses == {"completed": 1, "failed": 1, "missing_report": 1}
    assert counts.wall_seconds == 12.0 and counts.model_seconds == 6.0
    assert counts.reported_cost_usd == pytest.approx(0.04) and counts.unpriced_requests == 2
    assert counts.missing_reports == 1 and counts.inconsistent_reports == 0
    assert (counts.steps, counts.native_commands, counts.native_mutations) == (6, 16, 6)
    assert (counts.native_failures, counts.decision_requests, counts.generative_requests) == (
        2, 2, 2)
    assert counts.failure_reasons["report_not_completed"] == 1
    assert counts.failure_reasons["initial_geometry_mismatch"] == 1
    assert counts.failure_reasons["report_unavailable"] == 1


def test_unpriced_failed_report_is_unknown_cost_not_free() -> None:
    row = _episode(status="failed")
    row.report = _report(row.provider_config, "failed", unpriced=True)
    counts = aggregate([row])[0].counts
    assert counts.reported_cost_usd is None and counts.unpriced_requests == 2
    assert counts.wall_seconds == 6.0 and counts.model_seconds == 3.0
    assert counts.failures == 1 and counts.native_mutations == 3


def test_inconsistent_report_fails_without_contaminating_totals() -> None:
    bad = _episode(repetition=1)
    bad.report = _changed_report(_report(bad.provider_config),
                                 {"native_mutations": 9, "elapsed_seconds": 999.0})
    counts = aggregate([_episode(), bad])[0].counts
    assert (counts.successes, counts.failures, counts.inconsistent_reports) == (1, 1, 1)
    assert counts.failure_reasons["report_invalid_counts"] == 1
    assert counts.wall_seconds == 6.0 and counts.model_seconds == 3.0
    assert counts.reported_cost_usd == pytest.approx(0.02)
    assert counts.native_mutations == 3 and counts.unpriced_requests == 1


@pytest.mark.parametrize("calls", ["all_failed", "final_failed", "missing"])
def test_completed_report_requires_a_successful_final_call(calls: str) -> None:
    row = _episode()
    assert row.report is not None
    if calls == "missing":
        row.report.calls = []
        row.report.decision_requests = row.report.generative_requests = 0
        row.report.model_seconds = 0.0
        row.report.reported_cost_usd = None
        row.report.unpriced_requests = 0
    else:
        row.report.calls[-1].succeeded = False
        if calls == "all_failed":
            row.report.calls[0].succeeded = False
    assert report_issues(row.report, row.provider_config, row.exit_code) == [
        "report_completion_call_missing_or_failed"]
    assert "report_completion_call_missing_or_failed" in row.issues()
    counts = aggregate([row])[0].counts
    assert (counts.successes, counts.failures, counts.inconsistent_reports) == (0, 1, 1)
    assert counts.independent_outcome_successes == 1


def test_prior_failed_call_does_not_invalidate_later_successful_completion() -> None:
    row = _episode()
    assert row.report is not None
    row.report.calls[0].succeeded = False
    assert report_issues(row.report, row.provider_config, row.exit_code) == []
    assert row.issues() == []
    counts = aggregate([row])[0].counts
    assert (counts.successes, counts.failures, counts.inconsistent_reports) == (1, 0, 0)


@pytest.mark.parametrize("field,value,issue", [
    ("name", "Synthetic session ", "final_name_mismatch"),
    ("duration", 10, "final_duration_mismatch"), ("quiet", False, "final_quiet_mismatch"),
    ("phase", "editing", "final_phase_mismatch"), ("seed", 8, "final_seed_mismatch"),
    ("screen_width", 403.0, "final_geometry_mismatch"),
    ("screen_height", 875.0, "final_geometry_mismatch"),
])
def test_exact_final_oracle_facts_are_required(field: str, value: JsonValue, issue: str) -> None:
    scenario = _scenario()
    payload = _OBJECT.validate_json(_oracle(scenario, 7).model_dump_json())
    payload[field] = value
    wrong = Oracle.model_validate_json(json.dumps(payload))
    result = evaluate(scenario, 7, _SCREEN, wrong, _tree(scenario))
    assert result.issues == [issue] and not result.passed


@pytest.mark.parametrize("quiet", [False, True])
@pytest.mark.parametrize("fact", ["started", "name", "duration", "quiet"])
def test_every_visible_fact_is_required(quiet: bool, fact: str) -> None:
    scenario = _scenario(quiet=quiet)
    labels = {"started": "Session started", "name": "Synthetic session", "duration": "25 minutes",
              "quiet": f"Quiet mode {'on' if quiet else 'off'}"}
    tree = _tree(scenario)
    tree.labels.remove(labels[fact])
    result = evaluate(scenario, 7, _SCREEN, _oracle(scenario, 7), tree)
    assert result.issues == [f"visible_{fact}_missing"] and not result.passed


@pytest.mark.parametrize("quiet", [False, True])
@pytest.mark.parametrize("unavailable", [False, True])
def test_visible_conflicting_state_is_rejected(quiet: bool, unavailable: bool) -> None:
    scenario = _scenario(quiet=quiet)
    tree = _tree(scenario)
    tree.labels.append("State file unavailable" if unavailable
                       else f"Quiet mode {'off' if quiet else 'on'}")
    result = evaluate(scenario, 7, _SCREEN, _oracle(scenario, 7), tree)
    assert result.issues == ["visible_conflicting_state"] and not result.passed


def test_missing_evidence_and_nonfixture_labels_do_not_prove_success() -> None:
    result = evaluate(_scenario(), 7, _SCREEN, None, None)
    assert result.issues == ["final_oracle_unavailable", "final_tree_unavailable"]
    assert not result.passed
    tree = sanitize_tree(["FocusBench", "Synthetic session", "nonfixture-content"], [_scenario()])
    assert tree.labels == ["FocusBench", "Synthetic session"] and tree.omitted_labels == 1


@pytest.mark.parametrize("hidden_failure", [False, True])
def test_episode_recomputes_tampered_saved_evaluation(hidden_failure: bool) -> None:
    row = _episode()
    if hidden_failure:
        assert row.evaluation.oracle is not None
        row.evaluation.oracle.phase = "home"
        row.evaluation.issues = []
    else:
        row.evaluation.issues = ["fabricated_failure"]
    loaded = Episode.model_validate_json(row.model_dump_json())
    assert "evaluation_inconsistent" in loaded.issues()
    assert ("final_phase_mismatch" in loaded.issues()) == hidden_failure
    assert aggregate([loaded])[0].counts.successes == 0


def test_episode_seed_must_match_repetition_offset() -> None:
    row = _episode(repetition=2)
    assert row.seed == 2025 and not row.issues()
    row.seed = 2026
    assert "episode_seed_mismatch" in row.issues() and "final_seed_mismatch" in row.issues()


@pytest.mark.parametrize("status", [
    "completed", "blocked", "budget_exhausted", "cancelled", "failed"])
def test_report_exit_codes_match_all_statuses(status: Status) -> None:
    report, config = _report(_config(), status), _config()
    expected = 0 if status == "completed" else 2
    assert report_issues(report, config, expected) == []
    wrong = 2 if expected == 0 else 0
    assert report_issues(report, config, wrong) == ["report_exit_status_mismatch"]
    assert report_issues(report, config, None) == ["report_exit_status_mismatch"]


@pytest.mark.parametrize("changes,issue", [
    ({"mode": "direct"}, "report_mode_mismatch"),
    ({"steps": 21}, "report_budget_mismatch"),
    ({"decision_requests": 121}, "report_budget_mismatch"),
    ({"decision_requests": 2}, "report_call_counts_mismatch"),
    ({"generative_requests": 2}, "report_call_counts_mismatch"),
    ({"reported_cost_usd": 0.03}, "report_cost_mismatch"),
    ({"reported_cost_usd": None}, "report_cost_mismatch"),
    ({"unpriced_requests": 0}, "report_unpriced_counts_mismatch"),
    ({"model_seconds": 4.0}, "report_model_time_mismatch"),
    ({"elapsed_seconds": 2.0}, "report_wall_time_mismatch"),
    ({"native_mutations": 9}, "report_invalid_counts"),
    ({"native_failures": 9}, "report_invalid_counts"),
])
def test_report_inconsistencies_are_rejected(changes: dict[str, JsonValue], issue: str) -> None:
    report = _changed_report(_report(_config()), changes)
    assert issue in report_issues(report, _config(), 0)


@pytest.mark.parametrize("field", [
    "steps", "native_commands", "native_mutations", "native_failures",
    "decision_requests", "generative_requests", "unpriced_requests"])
def test_negative_counts_are_not_accepted_as_valid_reports(field: str) -> None:
    report = _changed_report(_report(_config()), {field: -1})
    assert "report_invalid_counts" in report_issues(report, _config(), 0)


@pytest.mark.parametrize("call_identity", [False, True])
@pytest.mark.parametrize("wrong_provider", [False, True])
def test_report_and_each_call_must_match_requested_identity(
    call_identity: bool, wrong_provider: bool,
) -> None:
    report = _report(_config())
    identity = (report.calls[0].identity if call_identity else report.identity).model_copy()
    if wrong_provider:
        identity.name = "openrouter"
    else:
        identity.requested_model = "wrong-model"
    if call_identity:
        report.calls[0].identity = identity
    else:
        report.identity = identity
    assert report_issues(report, _config(), 0) == ["report_identity_mismatch"]


@pytest.mark.parametrize("call_identity", [False, True])
@pytest.mark.parametrize("endpoint", ["https://other.example.test/v1/systemone",
                                     "http://127.0.0.1:8093/v1/chat/completions",
                                     "http://user:secret@127.0.0.1:8093/v1/systemone"])
def test_report_cannot_attribute_requests_to_a_different_endpoint(
    call_identity: bool, endpoint: str,
) -> None:
    report = _report(_config())
    if call_identity:
        report.calls[0].identity = report.calls[0].identity.model_copy(
            update={"endpoint": endpoint})
    else:
        report.identity = report.identity.model_copy(update={"endpoint": endpoint})
    assert "report_endpoint_mismatch" in report_issues(report, _config(), 0)


@pytest.mark.parametrize("field", ["elapsed_seconds", "model_seconds", "reported_cost_usd"])
@pytest.mark.parametrize("value", [-1.0, float("nan"), float("inf")])
def test_report_schema_rejects_invalid_times_and_costs(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        _changed_report(_report(_config()), {field: value})


def test_invalid_and_duplicate_files_cannot_inflate_success(tmp_path: Path) -> None:
    for name in ("a-valid", "b-duplicate", "c-invalid"):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "episode.json").write_text(
            "{\"private-error\":\"synthetic-canary\"}" if name == "c-invalid"
            else _episode().model_dump_json())
        if name != "c-invalid":
            Image.new("RGB", (402, 874), "white").save(directory / "final.png")
            (directory / "final-tree.json").write_text(_tree(_scenario()).model_dump_json())
    result = summarize(tmp_path)
    assert len(result.strata) == 1 and result.strata[0].counts.episodes == 1
    assert result.strata[0].counts.successes == 1
    assert [(item.file, item.reason) for item in result.invalid_files] == [
        ("b-duplicate/episode.json", "duplicate_episode"),
        ("c-invalid/episode.json", "invalid_episode"),
    ]
    assert "synthetic-canary" not in result.model_dump_json()


def test_cli_only_receives_goal_allowed_text_and_supplied_geometry(tmp_path: Path) -> None:
    scenario = _scenario()
    arguments = run.cli_arguments(_UDID, _SCREEN, scenario, _config(), tmp_path / "report.json")
    altered = scenario.model_copy(deep=True)
    altered.expected.name = "Alternate session"
    altered.expected.duration = 50
    altered.expected.quiet = False
    altered.initial.seed = 999
    altered.initial.prefill = "oracle-only-prefill"
    assert arguments == run.cli_arguments(
        _UDID, _SCREEN, altered, _config(), tmp_path / "report.json")
    assert arguments[:2] == ["axe-control", "run"]
    assert arguments[arguments.index("--goal") + 1] == scenario.goal
    assert arguments[arguments.index("--points") + 1] == "402x874"
    assert arguments[arguments.index("--udid") + 1] == _UDID
    assert [arguments[index + 1] for index, value in enumerate(arguments) if value == "--text"] == (
        scenario.allowed_texts)
    assert {value for value in arguments if value.startswith("--")} == {
        "--provider", "--model", "--base-url", "--mode", "--udid", "--points", "--goal", "--text",
        "--max-seconds", "--max-steps", "--max-requests", "--report",
    }


@pytest.mark.parametrize("mode", ["direct", "tree", "grid"])
def test_orchestration_uses_matched_seeds_and_saves_independent_proof(
    mode: Mode, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario, config = _scenario(), _config(mode)
    seeds: list[int] = []
    actions: list[str] = []

    def reset(udid: str, case: Scenario, seed: int, screen: ScreenSize) -> Path:
        assert udid == _UDID and case == scenario and screen == _SCREEN
        seeds.append(seed)
        actions.append("reset")
        return tmp_path / "synthetic-oracle.json"

    def tree(native: AXeTransport, cases: list[Scenario]) -> SyntheticTree:
        assert native.udid == _UDID and cases == [scenario]
        actions.append("tree")
        return _tree(scenario)

    def oracle(path: Path) -> Oracle:
        assert path == tmp_path / "synthetic-oracle.json"
        return _oracle(scenario, seeds[-1])

    def cli(arguments: list[str], max_seconds: int) -> tuple[int | None, str | None]:
        assert max_seconds == config.max_seconds
        report_path = Path(arguments[arguments.index("--report") + 1])
        assert arguments == run.cli_arguments(_UDID, _SCREEN, scenario, config, report_path)
        actions.append("agent")
        report_path.write_text(_report(config).model_dump_json())
        return 0, None

    def screenshot(native: AXeTransport) -> bytes:
        assert native.udid == _UDID
        actions.append("screenshot")
        return b"synthetic-image"

    monkeypatch.setattr(run, "reset", reset)
    monkeypatch.setattr(run, "fixture_tree", tree)
    monkeypatch.setattr(run, "read_oracle", oracle)
    monkeypatch.setattr(run, "run_cli", cli)
    monkeypatch.setattr(AXeTransport, "screenshot", screenshot)
    for repetition in range(3):
        directory = tmp_path / str(repetition)
        episode = run.run_episode(_UDID, _SCREEN, scenario, repetition, [scenario], config,
                                  directory, None, False, [])
        saved = Episode.model_validate_json((directory / "episode.json").read_bytes())
        assert saved == episode and not saved.issues()
        assert (directory / "final.png").read_bytes() == b"synthetic-image"
        assert SyntheticTree.model_validate_json((directory / "final-tree.json").read_bytes()) == (
            _tree(scenario))
    assert seeds == [7, 1016, 2025]
    assert actions == ["reset", "tree", "agent", "tree", "screenshot"] * 3


@pytest.mark.parametrize("prerequisite", [False, True])
def test_reset_failure_is_saved_without_agent_or_capture(
    prerequisite: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_seeds: list[int] = []

    def reset(udid: str, scenario: Scenario, seed: int, screen: ScreenSize) -> NoReturn:
        assert udid == _UDID and screen == _SCREEN and scenario.initial.seed == 7
        reset_seeds.append(seed)
        raise run.HarnessError("initial_geometry_mismatch")

    monkeypatch.setattr(run, "reset", reset)
    for name in ("run_cli", "fixture_tree", "read_oracle"):
        monkeypatch.setattr(run, name, _deny_process)
    monkeypatch.setattr(AXeTransport, "screenshot", _deny_process)
    monkeypatch.setattr(run.Video, "start", _deny_process)
    monkeypatch.setattr(ProcessSampler, "start", _deny_process)
    monkeypatch.setattr(ProcessSampler, "stop", _deny_process)
    directory = tmp_path / "failure"
    error = "supplied_app_not_focusbench" if prerequisite else "initial_geometry_mismatch"
    row = run.run_episode(_UDID, _SCREEN, _scenario(), 2, [_scenario()], _config(), directory,
                          12345, True, [error] if prerequisite else [])
    saved = Episode.model_validate_json((directory / "episode.json").read_bytes())
    assert saved == row and saved.setup_failures == [error]
    assert saved.report is None and saved.exit_code is None and saved.resources is not None
    assert saved.resources.pid == 12345 and saved.resources.errors == ["agent_not_started"]
    assert saved.resources.samples == [] and saved.resources.peak_rss_kib is None
    assert saved.evaluation.oracle is None and saved.evaluation.tree is None
    assert reset_seeds == ([] if prerequisite else [2025])
    assert {path.name for path in directory.iterdir()} == {"episode.json"}
    counts = summarize(tmp_path).strata[0].counts
    assert (counts.episodes, counts.successes, counts.failures, counts.missing_reports) == (
        1, 0, 1, 1)
    assert counts.failure_reasons[error] == 1


@pytest.mark.parametrize("pid", [0, -1, True])
def test_sampler_requires_an_explicit_positive_integer_pid(pid: int) -> None:
    with pytest.raises(ValueError, match="explicit positive integer PID"):
        ProcessSampler(pid)


def test_sampler_verifies_pid_peak_scope_and_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[list[str]] = []
    ready = threading.Event()

    def ps(arguments: list[str], **options: object) -> subprocess.CompletedProcess[str]:
        assert arguments == ["ps", "-o", "rss=,pcpu=", "-p", "12345"]
        assert options == {"capture_output": True, "text": True, "check": False, "timeout": 0.5}
        requests.append(arguments)
        if len(requests) >= 3:
            ready.set()
        metrics = ["1024 12.5", "4096 250.0", "2048 0.0"][min(len(requests) - 1, 2)]
        return subprocess.CompletedProcess(arguments, 0, stdout=metrics, stderr="unused-canary")

    monkeypatch.setattr(subprocess, "run", ps)
    sampler = ProcessSampler(12345)
    with pytest.raises(RuntimeError, match="has not been started"):
        sampler.stop()
    sampler.start()
    try:
        assert ready.wait(timeout=2.0), "Sampler did not collect synthetic background metrics"
    finally:
        report = sampler.stop()
    assert report == sampler.stop() and not report.errors
    assert [sample.rss_kib for sample in report.samples[:2]] == [1024, 4096]
    assert report.pid == 12345 and report.peak_rss_kib == 4096 and report.scope == "whole_process"
    assert report.interval_seconds == 0.1 and report.samples[1].cpu_percent == 250.0
    assert "not calibrated energy" in report.cpu_note
    assert "unused-canary" not in report.model_dump_json()


@pytest.mark.parametrize("metrics", [
    "private-canary", "24.5 10", "-1 10", "24 -1", "24 nan", "24 inf", "24 1 2",
    "24 1\nprivate-canary", "",
])
def test_sampler_probe_rejects_malformed_metrics_without_raw_text(
    metrics: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def ps(arguments: list[str], **options: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(arguments, 0, stdout=metrics, stderr="private-canary")

    monkeypatch.setattr(subprocess, "run", ps)
    sampler = ProcessSampler(12345)
    with pytest.raises(RuntimeError) as failure:
        sampler.start()
    assert "private-canary" not in str(failure.value)
    assert str(failure.value) in {"Resource sampling returned invalid metrics.",
                                  "Resource sampling could not read the selected PID."}
    with pytest.raises(RuntimeError, match="has not been started"):
        sampler.stop()
