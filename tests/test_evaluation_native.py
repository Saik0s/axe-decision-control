"""Offline evidence grading through the public evaluator, never inference or AXe."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import NoReturn

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
RECORDED = ROOT / "results/native-comparison"


@pytest.fixture(autouse=True)
def no_live_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    def deny(*args: object, **kwargs: object) -> NoReturn:
        pytest.fail("Offline evaluation attempted a subprocess or HTTP request")

    monkeypatch.setattr(subprocess, "run", deny)
    monkeypatch.setattr(subprocess, "Popen", deny)
    monkeypatch.setattr(httpx.Client, "send", deny)
    monkeypatch.setattr(httpx.AsyncClient, "send", deny)


def partial_matrix(root: Path) -> Path:
    root.mkdir()
    for name in ("expected-matrix.json", "matrix-run.json"):
        shutil.copyfile(RECORDED / name, root / name)
    relative = Path("gpt-direct/basic/repeat-0")
    case = root / relative
    case.mkdir(parents=True)
    for name in ("episode.json", "final-tree.json", "final.png", "original.mp4"):
        shutil.copyfile(RECORDED / relative / name, case / name)
    return case / "episode.json"


def test_recorded_native_evidence_regrades_without_inference() -> None:
    from evals.native import grade

    report = grade(RECORDED)
    assert report.data_integrity_ok and report.denominator_complete
    assert report.counts.expected == report.counts.matched == 105
    assert report.counts.strict_passes == report.counts.controller_complete == 46
    assert report.counts.native_outcome_reached == 58
    assert report.counts.strict_failures == 59
    assert report.counts.saved_proof_complete == 105
    assert not any(error.category == "data_integrity" for error in report.quality_errors)
    assert {error.category for error in report.quality_errors} == {
        "controller_incomplete", "native_outcome_not_reached"}
    assert len(report.evaluator_sha256) == 64
    assert report.frozen_implementation_fingerprint


def test_missing_and_malformed_attempts_keep_expected_denominator(tmp_path: Path) -> None:
    from evals.native import grade

    root = tmp_path / "matrix"
    episode = partial_matrix(root)
    report = grade(root)
    assert report.counts.expected == 105 and report.counts.matched == 1
    assert report.counts.missing == 104 and report.counts.strict_passes == 1
    assert not report.denominator_complete
    assert any(error.category == "incomplete_denominator" for error in report.quality_errors)
    episode.write_text('{"goal":"private-canary"}')
    report = grade(root)
    assert report.counts.expected == 105 and report.counts.matched == 0
    assert report.counts.missing == 105 and report.counts.strict_passes == 0
    assert not report.data_integrity_ok
    assert "private-canary" not in report.model_dump_json()


@pytest.mark.parametrize("damage", ["endpoint", "proof", "evaluation", "seed"])
def test_data_integrity_errors_are_separate_from_controller_claims(
    tmp_path: Path, damage: str,
) -> None:
    from evals.native import grade

    root = tmp_path / "matrix"
    path = partial_matrix(root)
    payload = json.loads(path.read_text())
    if damage == "endpoint":
        payload["report"]["identity"]["endpoint"] = "https://different.example.test"
    elif damage == "proof":
        (path.parent / "final.png").write_bytes(b"invalid PNG")
    elif damage == "seed":
        payload["seed"] += 1
    else:
        payload["evaluation"]["issues"] = ["invented private-canary"]
    path.write_text(json.dumps(payload))
    report = grade(root)
    assert report.counts.expected == 105 and report.counts.matched == 1
    assert report.counts.strict_passes == 0
    assert not report.data_integrity_ok
    assert any(error.category == "data_integrity" for error in report.quality_errors)
    assert "private-canary" not in report.model_dump_json()


def test_missing_frozen_matrix_never_becomes_a_one_episode_benchmark(tmp_path: Path) -> None:
    from evals.native import grade

    report = grade(tmp_path)
    assert report.counts.expected == report.counts.missing == 105
    assert not report.data_integrity_ok and not report.denominator_complete


def test_cli_exits_for_evidence_validity_and_optional_all_pass_policy(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    from evals.native import main

    output = tmp_path / "regrade.json"
    assert main(["--input", str(RECORDED), "--output", str(output)]) == 0
    report = json.loads(output.read_text())
    assert report["counts"]["strict_passes"] == 46
    assert main(["--input", str(RECORDED), "--require-all-pass"]) == 2
    assert '"strict_failures": 59' in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["--input", str(RECORDED), "--output", str(output)])
    assert json.loads(output.read_text()) == report


def test_cli_refuses_to_write_into_evidence_input(tmp_path: Path) -> None:
    from evals.native import main

    root = tmp_path / "matrix"
    partial_matrix(root)
    output = root / "new-regrade.json"
    with pytest.raises(SystemExit):
        main(["--input", str(root), "--output", str(output)])
    assert not output.exists()
