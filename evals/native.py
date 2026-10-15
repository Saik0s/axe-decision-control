"""Regrade saved native evidence against its frozen 105-slot expected matrix."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from axe_control.decisions import Count, StrictModel
from benchmarks.matrix import ExpectedMatrix, files_digest
from benchmarks.summarize import (
    Episode,
    evaluate,
    report_issues,
    saved_proof_issues,
    summarize,
)

ROOT = Path(__file__).resolve().parents[1]
Category = Literal["data_integrity", "incomplete_denominator", "controller_incomplete",
                   "native_outcome_not_reached"]


class QualityError(StrictModel):
    category: Category
    code: str
    cell: str | None = None
    scenario: str | None = None
    repetition: Count | None = None


class Counts(StrictModel):
    expected: Count = 105
    observed_files: Count
    matched: Count
    missing: Count
    unexpected: Count
    strict_passes: Count
    strict_failures: Count
    controller_complete: Count
    native_outcome_reached: Count
    saved_proof_complete: Count


class NativeEvaluation(StrictModel):
    schema_version: Literal[1] = 1
    kind: Literal["offline_native_evidence"] = "offline_native_evidence"
    evaluated_utc: str
    evaluator_sha256: str
    frozen_implementation_fingerprint: str | None
    data_integrity_ok: bool
    denominator_complete: bool
    counts: Counts
    quality_errors: list[QualityError]
    caveat: str = (
        "Regrading saved synthetic fixture evidence, not a fresh native/model run. "
        "Controller completion and independent native outcome are separate. "
        "Missing slots remain in the 105-slot denominator; strict_failures counts "
        "matched attempts only. Saved PNG validity does not establish visual semantics. "
        "These observations do not establish general-app accuracy or causal mode effects."
    )


def grade(directory: Path) -> NativeEvaluation:
    """Read only: recompute oracle facts and saved proof, ignoring saved summary totals."""
    expected_path = directory / "expected-matrix.json"
    summary = summarize(directory, expected_path)
    coverage = summary.coverage
    assert coverage is not None  # Passing an explicit expectation always audits coverage.
    errors = [QualityError(category="data_integrity", code=issue) for issue in coverage.issues]
    errors.extend(QualityError(category="data_integrity", code=item.reason)
                  for item in summary.invalid_files)
    if coverage.unexpected:
        errors.append(QualityError(category="incomplete_denominator",
                                   code="unexpected_episode_files"))
    try:
        expected = ExpectedMatrix.model_validate_json(expected_path.read_bytes())
    except (OSError, ValidationError):
        expected = None
    expected_count = 105
    missing = expected_count - coverage.matched
    if missing:
        errors.append(QualityError(category="incomplete_denominator",
                                   code="expected_slots_missing"))
    strict_passes = controller_complete = native_outcome = proof_complete = 0
    missing_slots = {(slot.cell, slot.scenario, slot.repetition) for slot in coverage.missing}
    if expected is not None:
        for cell in expected.cells:
            for scenario in expected.scenarios:
                for repetition in range(expected.repeats):
                    if (cell.id, scenario.id, repetition) in missing_slots:
                        continue
                    path = (directory / cell.id / scenario.id / f"repeat-{repetition}"
                            / "episode.json")
                    episode = Episode.model_validate_json(path.read_bytes())
                    proof_issues = saved_proof_issues(episode, path.parent)
                    checked = evaluate(scenario, episode.seed, expected.screen,
                                       episode.evaluation.oracle, episode.evaluation.tree)
                    integrity = list(proof_issues)
                    if episode.setup_failures:
                        integrity.append("episode_setup_failure")
                    if episode.proof_failures:
                        integrity.append("episode_capture_failure")
                    seed_matches = episode.seed == scenario.initial.seed + 1009 * repetition
                    if not seed_matches:
                        integrity.append("episode_seed_mismatch")
                    if episode.evaluation.issues != checked.issues:
                        integrity.append("evaluation_inconsistent")
                    accounting = (report_issues(episode.report, cell.config, episode.exit_code)
                                  if episode.report is not None else ["report_unavailable"])
                    integrity.extend(accounting)
                    complete = (episode.report is not None and not accounting
                                and episode.report.status == "completed")
                    outcome = checked.passed and seed_matches
                    controller_complete += complete
                    native_outcome += outcome
                    proof_complete += not proof_issues
                    strict_passes += not episode.issues() and not proof_issues
                    for code in sorted(set(integrity)):
                        errors.append(QualityError(category="data_integrity", code=code,
                                                  cell=cell.id, scenario=scenario.id,
                                                  repetition=repetition))
                    if not complete:
                        errors.append(QualityError(category="controller_incomplete",
                                                  code="controller_not_completed", cell=cell.id,
                                                  scenario=scenario.id, repetition=repetition))
                    if not outcome:
                        for code in checked.issues or ["episode_seed_mismatch"]:
                            errors.append(QualityError(category="native_outcome_not_reached",
                                                      code=code, cell=cell.id,
                                                      scenario=scenario.id, repetition=repetition))
    sources = [Path(__file__), ROOT / "benchmarks/matrix.py", ROOT / "benchmarks/summarize.py",
               ROOT / "benchmarks/resources.py", ROOT / "src/axe_control/models.py",
               ROOT / "src/axe_control/decisions.py"]
    return NativeEvaluation(
        evaluated_utc=datetime.now(UTC).isoformat(),
        evaluator_sha256=files_digest(sources, ROOT),
        frozen_implementation_fingerprint=expected.frozen.fingerprint() if expected else None,
        data_integrity_ok=not any(error.category == "data_integrity" for error in errors),
        denominator_complete=(coverage.matched == expected_count and not coverage.missing
                              and not coverage.unexpected and not summary.invalid_files),
        counts=Counts(observed_files=sum(1 for _ in directory.rglob("episode.json")),
                      matched=coverage.matched, missing=missing,
                      unexpected=len(coverage.unexpected), strict_passes=strict_passes,
                      strict_failures=coverage.matched - strict_passes,
                      controller_complete=controller_complete,
                      native_outcome_reached=native_outcome,
                      saved_proof_complete=proof_complete),
        quality_errors=errors,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Saved native matrix directory")
    parser.add_argument("--output", type=Path,
                        help="Fresh JSON file outside the evidence directory")
    parser.add_argument("--require-all-pass", action="store_true",
                        help="Also exit 2 for controller/task failures; default: evidence validity")
    args = parser.parse_args(argv)
    try:
        if args.output and args.output.resolve().is_relative_to(args.input.resolve()):
            parser.error("Output must be outside the evidence directory; inputs are read-only")
        if args.output and args.output.exists():
            parser.error("Output already exists; choose a fresh regrade destination")
        report = grade(args.input)
        serialized = report.model_dump_json(indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(serialized)
    except (OSError, ValueError):
        parser.exit(2, "Evidence evaluation or output write failed; no raw input is logged.\n")
    print(serialized, end="")
    valid = report.data_integrity_ok and report.denominator_complete
    return 0 if valid and (not args.require_all_pass or report.counts.strict_passes == 105) else 2


if __name__ == "__main__":
    raise SystemExit(main())
