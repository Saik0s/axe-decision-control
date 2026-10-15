"""Saved evidence and frozen matrix regressions, with all live execution forbidden."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

import httpx
import pytest
from PIL import Image
from pydantic import ValidationError

from axe_control.decisions import ModelCall, ProviderIdentity, ProviderUsage
from axe_control.models import RunReport, ScreenSize
from benchmarks import matrix
from benchmarks.summarize import (
    Episode,
    Oracle,
    Proof,
    SyntheticTree,
    evaluate,
    load_manifest,
    saved_proof_issues,
    summarize,
)
from benchmarks.summarize import (
    main as summarize_main,
)


def deny_live(*arguments: object, **options: object) -> NoReturn:
    pytest.fail("Live execution is forbidden in benchmark review tests")


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "Popen", deny_live)
    monkeypatch.setattr(subprocess, "run", deny_live)
    monkeypatch.setattr(httpx.Client, "send", deny_live)
    monkeypatch.setattr(httpx.AsyncClient, "send", deny_live)


def expected_matrix() -> matrix.ExpectedMatrix:
    return matrix.ExpectedMatrix(
        screen=ScreenSize(width=402.0, height=874.0),
        scenarios=load_manifest(matrix.ROOT / "benchmarks/scenarios.json"),
        cells=matrix.cells("Winnow-12B", "http://127.0.0.1:8091",
                           "https://openrouter.ai/api", 300, 20, 120),
        frozen=matrix.Snapshot(source_sha256="a" * 64, runtime_package_sha256="b" * 64,
                               fixture_sha256="c" * 64, python="3.13.0", system="Test",
                               machine="synthetic", packages={}, simulator_runtime="iOS test"),
    )


def episode(expected: matrix.ExpectedMatrix, cell: matrix.Cell,
            index: int = 0, repetition: int = 0) -> Episode:
    scenario = expected.scenarios[index]
    facts = scenario.expected
    seed = scenario.initial.seed + 1009 * repetition
    oracle = Oracle(phase=facts.phase, name=facts.name, duration=facts.duration,
                    quiet=facts.quiet, seed=seed, screen_width=expected.screen.width,
                    screen_height=expected.screen.height)
    tree = SyntheticTree(labels=["FocusBench", "Session started", facts.name,
                                f"{facts.duration} minutes",
                                f"Quiet mode {'on' if facts.quiet else 'off'}"])
    identity = ProviderIdentity(name=cell.config.provider, requested_model=cell.config.model,
                                endpoint=cell.config.base_url + (
                                    "/v1/chat/completions" if cell.config.mode == "direct" else
                                    "/v1/systemone" if cell.config.provider == "winnow" else
                                    "/alpha/decisions"),
                                local=cell.config.provider == "winnow")
    calls = [ModelCall(kind="generative" if cell.config.mode == "direct" else "decision",
                       succeeded=True, identity=identity, usage=ProviderUsage(request_ms=1.0))
             for _ in range(2 if cell.config.mode == "direct" else 3)]
    report = RunReport(mode=cell.config.mode, status="completed", reason="synthetic",
                       steps=1, native_commands=0, native_failures=0, native_mutations=0,
                       decision_requests=sum(call.kind == "decision" for call in calls),
                       generative_requests=sum(call.kind == "generative" for call in calls),
                       elapsed_seconds=1.0, model_seconds=len(calls) / 1000,
                       reported_cost_usd=None, unpriced_requests=len(calls),
                       identity=identity, events=[], calls=calls)
    return Episode(scenario=scenario, repetition=repetition, seed=seed, screen=expected.screen,
                   provider_config=cell.config, report=report, exit_code=0,
                   evaluation=evaluate(scenario, seed, expected.screen, oracle, tree),
                   setup_failures=[], proof=Proof(screenshot="final.png", tree="final-tree.json"))


def save(directory: Path, row: Episode, *, proof: bool = True) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "episode.json"
    path.write_text(row.model_dump_json())
    if proof:
        Image.new("RGB", (2, 2), "white").save(directory / "final.png", format="PNG")
        assert row.evaluation.tree is not None
        (directory / "final-tree.json").write_text(row.evaluation.tree.model_dump_json())
    return path


def freeze(root: Path, expected: matrix.ExpectedMatrix, *, finished: bool = True) -> None:
    root.mkdir(parents=True, exist_ok=True)
    raw = expected.model_dump_json().encode()
    (root / "expected-matrix.json").write_bytes(raw)
    fingerprint = expected.frozen.fingerprint()
    record = matrix.MatrixRun(expected_sha256=hashlib.sha256(raw).hexdigest(),
                              started_utc="2026-10-05T00:00:00+00:00",
                              finished_utc="2026-10-05T01:00:00+00:00" if finished else None,
                              cells=[matrix.CellResult(
                                  cell=cell.id, status="finished" if finished else "pending",
                                  exit_code=0 if finished else None,
                                  before=fingerprint if finished else None,
                                  after=fingerprint if finished else None)
                                  for cell in expected.cells])
    matrix.write_record(root, record)


def save_cell(root: Path, expected: matrix.ExpectedMatrix, cell: matrix.Cell) -> None:
    for index, scenario in enumerate(expected.scenarios):
        for repetition in range(3):
            save(root / cell.id / scenario.id / f"repeat-{repetition}",
                 episode(expected, cell, index, repetition))


@pytest.mark.parametrize("kind", ["screenshot", "tree", "video"])
@pytest.mark.parametrize("empty", [False, True])
def test_missing_or_empty_proof_preserves_embedded_success_and_denominator(
    tmp_path: Path, kind: str, empty: bool,
) -> None:
    expected = expected_matrix()
    row = episode(expected, expected.cells[0])
    if kind == "video":
        row.proof.video = "original.mp4"
    save(tmp_path / "case", row, proof=kind == "video")
    if empty:
        filename = {"screenshot": "final.png", "tree": "final-tree.json",
                    "video": "original.mp4"}[kind]
        (tmp_path / "case" / filename).write_bytes(b"")
    counts = summarize(tmp_path).strata[0].counts
    assert (counts.episodes, counts.successes, counts.failures) == (1, 0, 1)
    assert counts.independent_outcome_successes == 1 and counts.saved_proof_complete == 0
    assert counts.failure_reasons["proof_incomplete"] == 1
    assert counts.statuses == {"completed": 1}
    assert not summarize(tmp_path).invalid_files


@pytest.mark.parametrize("reference", ["../outside.png", "/outside.png", "C:\\proof.png",
                                       "https://example.test/proof.png", ""])
def test_unsafe_paths_are_rejected_before_opening_media(
    tmp_path: Path, reference: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = expected_matrix()
    row = episode(expected, expected.cells[0])
    row.proof.screenshot = reference
    monkeypatch.setattr(Image, "open", deny_live)
    assert "proof_screenshot_invalid" in saved_proof_issues(row, tmp_path)


@pytest.mark.parametrize("kind", ["screenshot", "tree", "video"])
def test_symlink_escape_is_rejected(tmp_path: Path, kind: str) -> None:
    expected = expected_matrix()
    row = episode(expected, expected.cells[0])
    directory = tmp_path / "case"
    save(directory, row)
    external = tmp_path / "outside"
    external.write_bytes(b"not authorized proof")
    (directory / "escaped").symlink_to(external)
    if kind == "screenshot":
        row.proof.screenshot = "escaped"
    elif kind == "tree":
        row.proof.tree = "escaped"
    else:
        row.proof.video = "escaped"
    assert f"proof_{kind}_invalid" in saved_proof_issues(row, directory)


@pytest.mark.parametrize("kind", ["bad-png", "wrong-image-format", "bad-tree", "empty-tree",
                                  "tree-mismatch"])
def test_nonempty_but_invalid_or_mismatched_proof_fails(tmp_path: Path, kind: str) -> None:
    expected = expected_matrix()
    row = episode(expected, expected.cells[0])
    save(tmp_path, row)
    if kind == "bad-png":
        (tmp_path / "final.png").write_bytes(b"not a png")
    elif kind == "wrong-image-format":
        Image.new("RGB", (2, 2)).save(tmp_path / "final.png", format="JPEG")
    else:
        (tmp_path / "final-tree.json").write_text(
            "invalid" if kind == "bad-tree" else SyntheticTree(
                labels=[] if kind == "empty-tree" else ["FocusBench"]).model_dump_json())
    counts = summarize(tmp_path).strata[0].counts
    assert counts.successes == 0 and counts.independent_outcome_successes == 1
    assert counts.saved_proof_complete == 0 and counts.failure_reasons["proof_incomplete"] == 1


def test_valid_media_is_separate_from_failed_model_and_embedded_outcome(tmp_path: Path) -> None:
    expected = expected_matrix()
    row = episode(expected, expected.cells[0])
    assert row.evaluation.oracle is not None
    row.evaluation.oracle.phase = "editing"
    row.report = None
    row.exit_code = None
    row.setup_failures = ["fixture_setup_failed"]
    save(tmp_path, row)
    counts = summarize(tmp_path).strata[0].counts
    assert counts.episodes == counts.failures == counts.saved_proof_complete == 1
    assert counts.independent_outcome_successes == counts.successes == 0
    assert counts.failure_reasons["fixture_setup_failed"] == 1
    assert counts.failure_reasons["report_unavailable"] == 1
    assert counts.failure_reasons["final_phase_mismatch"] == 1


def test_full_105_episode_matrix_has_exact_coverage(tmp_path: Path) -> None:
    expected = expected_matrix()
    freeze(tmp_path, expected)
    for cell in expected.cells:
        save_cell(tmp_path, expected, cell)
    summary = summarize(tmp_path)
    assert summary.coverage is not None and summary.coverage.complete
    assert (summary.coverage.expected, summary.coverage.observed, summary.coverage.matched) == (
        105, 105, 105)
    assert len(summary.strata) == 35 and not summary.invalid_files
    assert sum(item.counts.successes for item in summary.strata) == 105
    assert sum(item.counts.saved_proof_complete or 0 for item in summary.strata) == 105


@pytest.mark.parametrize("episodes_fail,ledger_fails", [(True, False), (False, True),
                                                       (True, True), (False, False)])
def test_cell_ledger_must_agree_with_complete_matched_episode_results(
    tmp_path: Path, episodes_fail: bool, ledger_fails: bool,
) -> None:
    expected = expected_matrix()
    freeze(tmp_path, expected)
    cell = expected.cells[0]
    for index, scenario in enumerate(expected.scenarios):
        for repetition in range(3):
            row = episode(expected, cell, index, repetition)
            if episodes_fail:
                assert row.report is not None
                row.report.status = "blocked"
                row.exit_code = 2
            save(tmp_path / cell.id / scenario.id / f"repeat-{repetition}", row)
    record = matrix.MatrixRun.model_validate_json((tmp_path / "matrix-run.json").read_bytes())
    if ledger_fails:
        record.cells[0].status = "failed"
        record.cells[0].exit_code = 2
    matrix.write_record(tmp_path, record)
    summary = summarize(tmp_path)
    assert summary.coverage is not None and summary.coverage.matched == 15
    assert ("matrix_cell_episode_status_mismatch" in summary.coverage.issues) == (
        episodes_fail != ledger_fails)
    assert sum(item.counts.failures for item in summary.strata) == (15 if episodes_fail else 0)


@pytest.mark.parametrize("episodes_fail,ledger_fails", [(False, True), (True, True),
                                                       (True, False)])
def test_partial_cell_only_rejects_a_proven_ledger_contradiction(
    tmp_path: Path, episodes_fail: bool, ledger_fails: bool,
) -> None:
    expected = expected_matrix()
    freeze(tmp_path, expected)
    cell = expected.cells[0]
    row = episode(expected, cell)
    if episodes_fail:
        assert row.report is not None
        row.report.status = "blocked"
        row.exit_code = 2
    save(tmp_path / cell.id / row.scenario.id / "repeat-0", row)
    record = matrix.MatrixRun.model_validate_json((tmp_path / "matrix-run.json").read_bytes())
    if ledger_fails:
        record.cells[0].status = "failed"
        record.cells[0].exit_code = 2
    matrix.write_record(tmp_path, record)
    summary = summarize(tmp_path)
    assert summary.coverage is not None and not summary.coverage.complete
    assert len(summary.coverage.missing) == 104
    assert summary.coverage.issues == (
        ["matrix_cell_episode_status_mismatch"] if episodes_fail and not ledger_fails else [])


def test_interrupted_suite_reports_104_missing_and_nonzero_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    expected = expected_matrix()
    freeze(tmp_path, expected, finished=False)
    row = episode(expected, expected.cells[0])
    save(tmp_path / expected.cells[0].id / row.scenario.id / "repeat-0", row)
    summary = summarize(tmp_path)
    assert summary.coverage is not None and not summary.coverage.complete
    assert summary.coverage.matched == 1 and len(summary.coverage.missing) == 104
    assert "matrix_run_unfinished" in summary.coverage.issues
    monkeypatch.setattr(sys, "argv", ["summarize", str(tmp_path)])
    assert summarize_main() == 2
    assert '"expected": 105' in capsys.readouterr().out


@pytest.mark.parametrize("mismatch", ["budget", "scenario", "geometry", "repetition",
                                      "layout", "duplicate", "malformed"])
def test_expected_matching_rejects_incompatible_or_duplicate_observations(
    tmp_path: Path, mismatch: str,
) -> None:
    expected = expected_matrix()
    freeze(tmp_path, expected)
    row = episode(expected, expected.cells[0])
    directory = tmp_path / expected.cells[0].id / row.scenario.id / "repeat-0"
    if mismatch == "budget":
        row.provider_config = row.provider_config.model_copy()
        row.provider_config.max_steps = 19
    elif mismatch == "scenario":
        row.scenario = row.scenario.model_copy()
        row.scenario.goal = "Changed synthetic goal"
    elif mismatch == "geometry":
        row.screen = ScreenSize(width=403.0, height=874.0)
    elif mismatch == "repetition":
        row.repetition = 3
    elif mismatch == "layout":
        directory = tmp_path / "incorrect-cell"
    path = save(directory, row)
    if mismatch == "duplicate":
        save(tmp_path / "copy", row)
    elif mismatch == "malformed":
        path.write_text("{}")
    summary = summarize(tmp_path)
    assert summary.coverage is not None and not summary.coverage.complete
    assert summary.coverage.matched == (1 if mismatch == "duplicate" else 0)
    assert len(summary.coverage.missing) == (104 if mismatch == "duplicate" else 105)
    if mismatch == "malformed":
        assert summary.invalid_files[0].reason == "invalid_episode"
    else:
        assert len(summary.coverage.unexpected) == 1
    if mismatch == "duplicate":
        assert sum(item.counts.episodes for item in summary.strata) == 1
        assert summary.invalid_files[0].reason == "duplicate_episode"


@pytest.mark.parametrize("change", ["frozen-file", "runtime", "pending"])
def test_frozen_implementation_and_run_record_are_checked(tmp_path: Path, change: str) -> None:
    expected = expected_matrix()
    freeze(tmp_path, expected)
    if change == "frozen-file":
        expected.screen.width = 403.0
        (tmp_path / "expected-matrix.json").write_text(expected.model_dump_json())
    else:
        record = matrix.MatrixRun.model_validate_json((tmp_path / "matrix-run.json").read_bytes())
        if change == "runtime":
            record.cells[0].after = "f" * 64
        else:
            record.cells[0].status = "pending"
        matrix.write_record(tmp_path, record)
    coverage = summarize(tmp_path).coverage
    assert coverage is not None and not coverage.complete
    issue = {"frozen-file": "expected_matrix_changed",
             "runtime": "implementation_or_runtime_changed",
             "pending": "matrix_cell_unfinished"}[change]
    assert issue in coverage.issues


def test_missing_or_invalid_expected_file_fails_closed(tmp_path: Path) -> None:
    assert summarize(tmp_path, tmp_path / "absent").coverage is not None
    (tmp_path / "expected-matrix.json").write_text("{}")
    coverage = summarize(tmp_path).coverage
    assert coverage is not None and coverage.issues == ["invalid_expected_matrix"]


@pytest.mark.parametrize("exit_code,issues", [(None, ["child_timeout"]),
                                           (1, []), (2, ["cell_metadata_unavailable"])])
def test_complete_episode_files_do_not_hide_harness_failure(
    tmp_path: Path, exit_code: int | None, issues: list[str],
) -> None:
    expected = expected_matrix()
    freeze(tmp_path, expected)
    for cell in expected.cells:
        save_cell(tmp_path, expected, cell)
    record = matrix.MatrixRun.model_validate_json((tmp_path / "matrix-run.json").read_bytes())
    record.cells[0].status = "failed"
    record.cells[0].exit_code = exit_code
    record.cells[0].issues = issues
    matrix.write_record(tmp_path, record)
    coverage = summarize(tmp_path).coverage
    assert coverage is not None and coverage.matched == 105
    assert not coverage.complete
    assert coverage.issues


@pytest.mark.parametrize("change", ["mode", "missing-cell", "scenario", "model-path"])
def test_frozen_schema_rejects_nonfinal_matrix(change: str) -> None:
    expected = expected_matrix()
    if change == "mode":
        expected.cells[1].config.mode = "direct"
    elif change == "missing-cell":
        expected.cells.pop()
    elif change == "scenario":
        expected.scenarios[0].id = "unexpected"
    else:
        for cell in expected.cells[4:]:
            cell.config.model = "/private/model"
    with pytest.raises(ValidationError):
        matrix.ExpectedMatrix.model_validate_json(expected.model_dump_json())


def options(tmp_path: Path) -> matrix.Options:
    result = matrix.Options()
    result.app = tmp_path / "FocusBench.app"
    result.app.mkdir()
    (result.app / "FocusBench").write_bytes(b"synthetic fixture")
    result.output = tmp_path / "matrix"
    result.udid = "11111111-2222-3333-4444-555555555555"
    result.scenarios = matrix.ROOT / "benchmarks/scenarios.json"
    result.points = "402x874"
    result.simulator_runtime = "iOS test"
    result.record = True
    result.server_pid = 12345
    result.plan_only = False
    return result


def test_matrix_preserves_failed_cell_and_runs_all_seven_without_logging_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = expected_matrix()
    opts = options(tmp_path)
    launched: list[str] = []
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-env-canary")
    monkeypatch.setattr(matrix, "snapshot", lambda app, runtime: expected.frozen)

    def execute(arguments: list[str], timeout: int) -> tuple[int, None]:
        cell_root = Path(arguments[arguments.index("--output") + 1])
        assert not cell_root.exists()
        cell = next(item for item in expected.cells if item.id == cell_root.name)
        launched.append(cell.id)
        assert arguments[:3] == [sys.executable, "-m", "benchmarks.run"]
        assert arguments[arguments.index("--repeats") + 1] == "3" and timeout == 6420
        assert ("--server-pid" in arguments) == (cell.config.provider == "winnow")
        save_cell(opts.output, expected, cell)
        return (2 if len(launched) == 1 else 0), None

    monkeypatch.setattr(matrix, "execute_cell", execute)
    assert matrix.run_matrix(opts, expected) == 2
    assert launched == list(matrix.CELL_IDS)
    record = matrix.MatrixRun.model_validate_json((opts.output / "matrix-run.json").read_bytes())
    assert record.cells[0].status == "failed"
    assert all(item.status == "finished" for item in record.cells[1:])
    assert summarize(opts.output).coverage is not None
    for filename in ("expected-matrix.json", "matrix-run.json", "summary.json"):
        text = (opts.output / filename).read_text()
        assert "synthetic-env-canary" not in text and str(tmp_path) not in text


def test_cancellation_preserves_record_and_stops_remaining_cells(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = expected_matrix()
    opts = options(tmp_path)
    launched: list[list[str]] = []
    monkeypatch.setattr(matrix, "snapshot", lambda app, runtime: expected.frozen)

    def execute(arguments: list[str], timeout: int) -> tuple[None, str]:
        launched.append(arguments)
        return None, "matrix_cancelled"

    monkeypatch.setattr(matrix, "execute_cell", execute)
    assert matrix.run_matrix(opts, expected) == 2 and len(launched) == 1
    record = matrix.MatrixRun.model_validate_json((opts.output / "matrix-run.json").read_bytes())
    assert record.cells[0].status == "cancelled"
    assert all(item.status == "pending" for item in record.cells[1:])
    assert (opts.output / "summary.json").is_file()


def test_plan_only_freezes_before_any_launch_and_refuses_root_reuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = expected_matrix()
    opts = options(tmp_path)
    opts.plan_only = True
    monkeypatch.setattr(matrix, "execute_cell", deny_live)
    assert matrix.run_matrix(opts, expected) == 0
    coverage = summarize(opts.output).coverage
    assert coverage is not None and len(coverage.missing) == 105
    with pytest.raises(FileExistsError):
        matrix.run_matrix(opts, expected)


def test_child_inherits_key_environment_and_discards_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-env-canary")

    class Child:
        def wait(self, timeout: int) -> int:
            assert timeout == 10
            return 2

    def launch(arguments: list[str], **kwargs: object) -> Child:
        assert arguments == ["synthetic-child"] and "env" not in kwargs
        assert kwargs == {"cwd": matrix.ROOT, "stdout": subprocess.DEVNULL,
                          "stderr": subprocess.DEVNULL, "start_new_session": True}
        assert os.environ["OPENROUTER_API_KEY"] == "synthetic-env-canary"
        return Child()

    monkeypatch.setattr(subprocess, "Popen", launch)
    assert matrix.execute_cell(["synthetic-child"], 10) == (2, None)


def test_snapshot_tracks_source_fixture_and_runtime_without_absolute_paths(tmp_path: Path) -> None:
    app = tmp_path / "FocusBench.app"
    app.mkdir()
    (app / "FocusBench").write_bytes(b"fixture one")
    first = matrix.snapshot(app, "iOS test")
    (app / "FocusBench").write_bytes(b"fixture two")
    second = matrix.snapshot(app, "iOS test")
    assert first.fixture_sha256 != second.fixture_sha256
    assert first.source_sha256 == second.source_sha256
    assert first.runtime_package_sha256 == second.runtime_package_sha256
    assert first.fingerprint() != second.fingerprint()
    assert str(tmp_path) not in first.model_dump_json()
    assert str(matrix.ROOT) not in first.model_dump_json()
