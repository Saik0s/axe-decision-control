"""Behavioral proof for the offline skill fixture/replay CLI."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from evals.skills import main

ROOT = Path(__file__).resolve().parents[1]
MINI_FIXTURES = """{
  "schema_version": 1, "provenance": "synthetic_unmeasured",
  "contract_sources": ["skills/axe-tree-control/SKILL.md"],
  "cases": [
    {"case_id": "control", "prompt": "Synthetic authorized tree task.",
     "expected": {"selected_skill": "axe-tree-control", "disposition": "ready",
                  "checks": ["fresh_observation", "bounded_execution"]},
     "rationale": "Use fresh targets and finite budgets."},
    {"case_id": "unrelated", "prompt": "Explain CSS grid without controlling a UI.",
     "expected": {"selected_skill": "none", "disposition": "unrelated", "checks": []},
     "rationale": "No simulator control request."}
  ]
}"""
CONTROL = ('{"case_id":"control","selected_skill":"axe-tree-control",'
           '"disposition":"ready","checks":["bounded_execution","fresh_observation"]}')
UNRELATED = ('{"case_id":"unrelated","selected_skill":"none",'
             '"disposition":"unrelated","checks":[]}')


@pytest.fixture
def fixture_file(tmp_path: Path) -> Path:
    path = tmp_path / "cases.json"
    path.write_text(MINI_FIXTURES, encoding="utf-8")
    return path


def replay(tmp_path: Path, fixture_file: Path, content: str) -> subprocess.CompletedProcess[str]:
    path = tmp_path / "responses.jsonl"
    path.write_text(content, encoding="utf-8")
    return run_cli("--fixtures", str(fixture_file), "--responses", str(path))


def run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-B", "-m", "evals.skills", *arguments],
        cwd=ROOT, capture_output=True, text=True, check=False, timeout=15,
    )


def test_default_checks_contract_without_claiming_performance() -> None:
    result = run_cli()
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "unmeasured"
    assert report["evidence"] == "fixture_contract_only"
    assert report["responses_supplied"] is False
    assert report["expected_cases"] >= 12
    assert "No responses" in report["note"]
    assert "success_rate" not in result.stdout
    assert "passed" not in report


def test_public_replay_grades_structured_records_without_execution_claims(
    tmp_path: Path, fixture_file: Path,
) -> None:
    result = replay(tmp_path, fixture_file, f"{CONTROL}\n{UNRELATED}\n")
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "graded"
    assert report["evidence"] == "structured_response_grading"
    assert report["skill_performance"] == "unmeasured"
    assert (report["expected_cases"], report["passed"], report["failed"], report["missing"]) == (
        2, 2, 0, 0)
    assert report["issues"] == []
    assert "no actual tool execution" in report["note"]
    assert "success_rate" not in result.stdout


def test_wrong_route_and_missing_safeguards_fail_complete_denominator(
    tmp_path: Path, fixture_file: Path,
) -> None:
    wrong = ('{"case_id":"control","selected_skill":"axe-grid-control",'
             '"disposition":"ready","checks":[]}')
    result = replay(tmp_path, fixture_file, f"{wrong}\n{UNRELATED}")
    report = json.loads(result.stdout)
    assert result.returncode == 1
    assert report["status"] == "graded"
    assert (report["expected_cases"], report["passed"], report["failed"]) == (2, 1, 1)
    assert report["cases"][0] == {
        "case_id": "control", "verdict": "mismatch",
        "mismatches": ["selected_skill", "checks"],
    }


def test_wrong_disposition_fails_without_dropping_the_record(
    tmp_path: Path, fixture_file: Path,
) -> None:
    wrong = CONTROL.replace('"ready"', '"blocked"')
    result = replay(tmp_path, fixture_file, f"{wrong}\n{UNRELATED}")
    report = json.loads(result.stdout)
    assert result.returncode == 1 and report["status"] == "graded"
    assert report["cases"][0]["mismatches"] == ["disposition"]
    assert (report["passed"], report["failed"], report["missing"]) == (1, 1, 0)


@pytest.mark.parametrize("content,passed,missing", [("", 0, 2), (CONTROL, 1, 1)])
def test_missing_responses_never_reduce_expected_denominator(
    tmp_path: Path, fixture_file: Path, content: str, passed: int, missing: int,
) -> None:
    result = replay(tmp_path, fixture_file, content)
    report = json.loads(result.stdout)
    assert result.returncode == 1 and report["status"] == "invalid"
    assert report["expected_cases"] == 2 and len(report["cases"]) == 2
    assert (report["passed"], report["failed"], report["missing"]) == (passed, 2 - passed, missing)


@pytest.mark.parametrize("bad", [
    "not-json-private-canary", "", "null", "[]",
    CONTROL[:-1] + ',"private":"private-canary"}',
    CONTROL.replace('"control"', "true"),
    CONTROL.replace('"control"', "NaN"),
    CONTROL.replace('"control"', "Infinity"),
    CONTROL.replace('"ready"', '"ready","disposition":"blocked"'),
    CONTROL.replace('"bounded_execution"', '"unsupported-check"'),
    CONTROL.replace('"bounded_execution"', '"fresh_observation"'),
    CONTROL.replace('"ready"', '"unrelated"'),
])
def test_malformed_records_are_visible_failures_without_raw_content(
    tmp_path: Path, fixture_file: Path, bad: str,
) -> None:
    result = replay(tmp_path, fixture_file, f"{CONTROL}\n{UNRELATED}\n{bad}\n")
    report = json.loads(result.stdout)
    assert result.returncode == 1 and report["status"] == "invalid"
    assert report["response_lines"] == 3
    assert report["issues"] == [{"line": 3, "reason": "invalid_response"}]
    assert report["expected_cases"] == 2
    assert "private-canary" not in result.stdout + result.stderr


def test_unknown_response_cannot_disappear_or_replace_a_missing_case(
    tmp_path: Path, fixture_file: Path,
) -> None:
    unknown = UNRELATED.replace('"unrelated"', '"unknown-private-canary"', 1)
    result = replay(tmp_path, fixture_file, f"{CONTROL}\n{unknown}")
    report = json.loads(result.stdout)
    assert result.returncode == 1 and report["status"] == "invalid"
    assert (report["expected_cases"], report["passed"], report["failed"], report["missing"]) == (
        2, 1, 1, 1)
    assert report["issues"] == [{"line": 2, "reason": "unknown_case"}]
    assert "unknown-private-canary" not in result.stdout


@pytest.mark.parametrize("first", [CONTROL, CONTROL.replace('"ready"', '"blocked"')])
def test_duplicate_records_invalidate_case_instead_of_selecting_a_good_answer(
    tmp_path: Path, fixture_file: Path, first: str,
) -> None:
    result = replay(tmp_path, fixture_file, f"{first}\n{UNRELATED}\n{CONTROL}")
    report = json.loads(result.stdout)
    assert result.returncode == 1 and report["status"] == "invalid"
    assert (report["passed"], report["failed"], report["missing"]) == (1, 1, 0)
    assert report["cases"][0]["verdict"] == "duplicate"
    assert report["issues"] == [{"line": 3, "reason": "duplicate_response"}]


@pytest.mark.parametrize("bad", [
    MINI_FIXTURES.replace('"schema_version": 1', '"schema_version": true'),
    MINI_FIXTURES.replace('"schema_version": 1', '"schema_version": Infinity'),
    MINI_FIXTURES.replace('"schema_version": 1', '"schema_version": 1,"schema_version": 1'),
    MINI_FIXTURES.replace('"case_id": "unrelated"', '"case_id": "control"'),
    MINI_FIXTURES.replace('"provenance": "synthetic_unmeasured"', '"provenance": "measured"'),
    MINI_FIXTURES.replace('"fresh_observation"', '"invented-safeguard"'),
    '{"private":"private-canary"}',
])
def test_fixture_contract_rejects_invalid_gold(
    fixture_file: Path, bad: str,
) -> None:
    fixture_file.write_text(bad, encoding="utf-8")
    result = run_cli("--fixtures", str(fixture_file))
    report = json.loads(result.stdout)
    assert result.returncode == 2 and report["status"] == "error"
    assert report["skill_performance"] == "unmeasured"
    assert "private-canary" not in result.stdout + result.stderr


@pytest.mark.parametrize("option", ["--responses", "--fixtures"])
def test_unreadable_input_is_an_explicit_sanitized_error(tmp_path: Path, option: str) -> None:
    result = run_cli(option, str(tmp_path / "private-canary.json"))
    assert result.returncode == 2
    assert json.loads(result.stdout)["status"] == "error"
    assert "private-canary" not in result.stdout + result.stderr


def test_non_utf8_response_is_an_input_error(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_bytes(b"\xff")
    result = run_cli("--responses", str(path))
    assert result.returncode == 2
    assert json.loads(result.stdout)["error"] == "Response file is unreadable"


def test_main_runs_without_network_or_native_processes(
    fixture_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def deny_boundary(*args: object, **kwargs: object) -> None:
        pytest.fail("Offline grading attempted network or native execution")

    monkeypatch.setattr("socket.socket", deny_boundary)
    monkeypatch.setattr(subprocess, "Popen", deny_boundary)
    path = tmp_path / "responses.jsonl"
    path.write_text(f"{CONTROL}\n{UNRELATED}", encoding="utf-8")
    assert main(["--fixtures", str(fixture_file)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "unmeasured"
    assert main(["--fixtures", str(fixture_file), "--responses", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["evidence"] == "structured_response_grading"


def test_canonical_cases_cover_independent_routing_and_safety_requirements() -> None:
    fixture = json.loads((ROOT / "evals" / "fixtures" / "skills.json").read_text())
    gold = {case["case_id"]: case["expected"] for case in fixture["cases"]}
    # Expectations come from the skill/provider contracts, not runner output.
    assert gold["tree-semantic-ready"]["selected_skill"] == "axe-tree-control"
    assert gold["grid-explicit-ready"]["selected_skill"] == "axe-grid-control"
    assert gold["unrelated-css-grid"]["selected_skill"] == "none"
    assert gold["negative-control-request"]["selected_skill"] == "none"
    assert gold["explicit-tree-skill"]["selected_skill"] == "axe-tree-control"
    assert gold["explicit-grid-skill"]["selected_skill"] == "axe-grid-control"
    for case_id, disposition, checks in [
        ("tree-missing-simulator", "clarify", {"explicit_simulator"}),
        ("tree-missing-geometry", "clarify", {"supplied_geometry"}),
        ("grid-missing-geometry", "clarify", {"supplied_geometry"}),
        ("hosted-tree-authorization", "clarify", {"destination_authorization"}),
        ("remote-winnow-authorization", "clarify", {"destination_authorization"}),
        ("jev-images-unsupported", "blocked", {"supported_image_provider"}),
        ("grid-oracle-leakage", "blocked", {"reject_oracle", "pixels_only"}),
    ]:
        assert gold[case_id]["disposition"] == disposition
        assert set(gold[case_id]["checks"]) == checks
