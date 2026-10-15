"""Validate synthetic skill cases or grade structured records; never run an agent."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Skill = Literal["axe-tree-control", "axe-grid-control", "none"]
Disposition = Literal["ready", "clarify", "blocked", "unrelated"]
Check = Literal[
    "fresh_observation", "bounded_execution", "independent_verification",
    "experimental_warning", "image_readiness", "pixels_only", "explicit_simulator",
    "supplied_geometry", "explicit_grid_request", "destination_authorization",
    "supported_image_provider", "reject_oracle", "approved_literal",
    "persistence_authorization",
]
CaseID = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,79}$")]
Count = Annotated[int, Field(ge=0)]
DEFAULT_FIXTURES = Path(__file__).parent / "fixtures" / "skills.json"
REPLAY_NOTE = (
    "Structured response grading only; no actual tool execution or measured skill/agent "
    "performance. Checks are recorded declarations, not execution evidence."
)


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False)


class Decision(StrictModel):
    selected_skill: Skill
    disposition: Disposition
    checks: list[Check] = Field(max_length=32)

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if len(self.checks) != len(set(self.checks)):
            raise ValueError("Checks must be unique")
        if (self.selected_skill == "none") != (self.disposition == "unrelated"):
            raise ValueError("Only unrelated decisions use no skill")
        if self.disposition in {"clarify", "blocked"} and not self.checks:
            raise ValueError("Stopped decisions require an explicit check")
        if self.disposition == "unrelated" and self.checks:
            raise ValueError("Unrelated decisions have no control checks")
        return self


class Case(StrictModel):
    case_id: CaseID
    prompt: str = Field(min_length=1, max_length=6000)
    expected: Decision
    rationale: str = Field(min_length=1, max_length=2000)


class Fixtures(StrictModel):
    schema_version: Annotated[int, Field(ge=1, le=1)]
    provenance: Literal["synthetic_unmeasured"]
    contract_sources: list[str] = Field(min_length=1, max_length=16)
    cases: list[Case] = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def unique_cases(self) -> Self:
        if len({case.case_id for case in self.cases}) != len(self.cases):
            raise ValueError("Case IDs must be unique")
        return self


class Response(Decision):
    """One JSONL record: a user-recorded declaration, not a tool transcript."""

    case_id: CaseID


class RecordIssue(StrictModel):
    line: Annotated[int, Field(ge=1)]
    reason: Literal["invalid_response", "unknown_case", "duplicate_response"]


class CaseGrade(StrictModel):
    case_id: CaseID
    verdict: Literal["passed", "mismatch", "missing", "duplicate"]
    mismatches: list[Literal["selected_skill", "disposition", "checks"]]


class ContractReport(StrictModel):
    status: Literal["unmeasured"] = "unmeasured"
    evidence: Literal["fixture_contract_only"] = "fixture_contract_only"
    responses_supplied: Literal[False] = False
    expected_cases: Annotated[int, Field(ge=1)]
    note: str = (
        "No responses supplied; synthetic cases are unmeasured. Fixture validity does not "
        "measure skill/agent performance. No tools or agents executed."
    )


class ReplayReport(StrictModel):
    status: Literal["graded", "invalid"]
    evidence: Literal["structured_response_grading"] = "structured_response_grading"
    skill_performance: Literal["unmeasured"] = "unmeasured"
    responses_supplied: Literal[True] = True
    expected_cases: Annotated[int, Field(ge=1)]
    response_lines: Count
    passed: Count
    failed: Count
    missing: Count
    issues: list[RecordIssue]
    cases: list[CaseGrade]
    note: str = REPLAY_NOTE

    @model_validator(mode="after")
    def complete_denominator(self) -> Self:
        if len(self.cases) != self.expected_cases:
            raise ValueError("Every expected case needs a grade")
        if len({case.case_id for case in self.cases}) != self.expected_cases:
            raise ValueError("Every grade needs a unique case ID")
        counts = Counter(case.verdict for case in self.cases)
        if self.passed != counts["passed"] or self.failed != self.expected_cases - self.passed:
            raise ValueError("Grade counts must use the complete expected denominator")
        if self.missing != counts["missing"]:
            raise ValueError("Missing count must match case grades")
        if (self.status == "invalid") != bool(self.issues or self.missing):
            raise ValueError("Invalid input cannot produce a valid grading status")
        return self


class InputError(ValueError):
    """A sanitized input error; never retain raw response/fixture content."""


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise InputError("Duplicate JSON key")
        result[key] = value
    return result


def _parse_json(content: str) -> object:
    # Reject duplicate keys before Pydantic can accept a last-key-wins decision.
    value: object = json.loads(content, object_pairs_hook=_unique_object)
    return value


def load_fixtures(path: Path = DEFAULT_FIXTURES) -> Fixtures:
    try:
        return Fixtures.model_validate(_parse_json(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        raise InputError("Fixture file is unreadable or violates the synthetic contract") from None


def grade_responses(fixtures: Fixtures, path: Path) -> ReplayReport:
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise InputError("Response file is unreadable") from None
    expected = {case.case_id: case.expected for case in fixtures.cases}
    records: dict[str, list[Response]] = {}
    issues: list[RecordIssue] = []
    lines = content.splitlines()
    for number, line in enumerate(lines, 1):
        try:
            record = Response.model_validate(_parse_json(line))
        except ValueError:
            issues.append(RecordIssue(line=number, reason="invalid_response"))
            continue
        if record.case_id not in expected:
            issues.append(RecordIssue(line=number, reason="unknown_case"))
            continue
        matching = records.setdefault(record.case_id, [])
        if matching:
            issues.append(RecordIssue(line=number, reason="duplicate_response"))
        matching.append(record)

    grades: list[CaseGrade] = []
    for case_id, gold in expected.items():
        matching = records.get(case_id, [])
        if not matching:
            grades.append(CaseGrade(case_id=case_id, verdict="missing", mismatches=[]))
        elif len(matching) != 1:
            grades.append(CaseGrade(case_id=case_id, verdict="duplicate", mismatches=[]))
        else:
            record = matching[0]
            mismatches: list[Literal["selected_skill", "disposition", "checks"]] = []
            if record.selected_skill != gold.selected_skill:
                mismatches.append("selected_skill")
            if record.disposition != gold.disposition:
                mismatches.append("disposition")
            if set(record.checks) != set(gold.checks):
                mismatches.append("checks")
            grades.append(CaseGrade(
                case_id=case_id, verdict="mismatch" if mismatches else "passed",
                mismatches=mismatches,
            ))
    passed = sum(grade.verdict == "passed" for grade in grades)
    missing = sum(grade.verdict == "missing" for grade in grades)
    return ReplayReport(
        status="invalid" if issues or missing else "graded", expected_cases=len(expected),
        response_lines=len(lines), passed=passed, failed=len(expected) - passed,
        missing=missing, issues=issues, cases=grades,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES,
                        help="Synthetic fixture JSON (default: bundled skills.json)")
    parser.add_argument("--responses", type=Path,
                        help="User-recorded JSONL decisions; no tools or agents are executed")
    args = parser.parse_args(argv)
    try:
        fixtures = load_fixtures(args.fixtures)
        report: ContractReport | ReplayReport
        if args.responses is None:
            report = ContractReport(expected_cases=len(fixtures.cases))
        else:
            report = grade_responses(fixtures, args.responses)
    except InputError as error:
        print(json.dumps({"status": "error", "skill_performance": "unmeasured",
                          "error": str(error)}))
        return 2
    print(report.model_dump_json(indent=2))
    if isinstance(report, ReplayReport) and (report.status == "invalid" or report.failed):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
