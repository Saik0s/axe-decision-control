#!/usr/bin/env python3
"""Strict fixture contracts, independent evaluation, and scenario-stratified results."""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from PIL import Image
from pydantic import Field, TypeAdapter, ValidationError, field_validator, model_validator

from axe_control.decisions import Count, Nonnegative, StrictModel
from axe_control.models import Mode, RunReport, ScreenSize

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmarks.resources import ResourceReport

Duration = Literal[5, 10, 15, 25, 50]
Provider = Literal["openrouter", "winnow"]


class Initial(StrictModel):
    seed: int
    duration: Duration
    quiet: bool
    prefill: Annotated[str, Field(max_length=2048)]
    scroll: bool


class Expected(StrictModel):
    name: Annotated[str, Field(min_length=1, max_length=2048)]
    duration: Duration
    quiet: bool
    phase: Literal["running"]


class Scenario(StrictModel):
    id: Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")]
    goal: Annotated[str, Field(min_length=1, max_length=8192)]
    allowed_texts: list[Annotated[str, Field(max_length=2048)]]
    initial: Initial
    expected: Expected

    @model_validator(mode="after")
    def allowed_name(self) -> Self:
        if self.expected.name not in self.allowed_texts:
            raise ValueError("Expected name must be explicitly allowed")
        return self


MANIFEST = TypeAdapter(list[Scenario])


def load_manifest(path: Path) -> list[Scenario]:
    scenarios = MANIFEST.validate_json(path.read_bytes(), strict=True)
    if not scenarios or len({scenario.id for scenario in scenarios}) != len(scenarios):
        raise ValueError("Manifest needs nonempty, unique scenario IDs")
    return scenarios


def safe_endpoint(value: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment):
        raise ValueError("Endpoint must omit credentials, query, and fragment")
    return value.rstrip("/")


class ProviderConfig(StrictModel):
    provider: Provider
    model: Annotated[str, Field(min_length=1)]
    mode: Mode
    base_url: str
    max_seconds: Annotated[int, Field(ge=1, le=3600)] = 300
    max_steps: Annotated[int, Field(ge=1, le=100)] = 20
    max_requests: Annotated[int, Field(ge=1, le=1000)] = 120

    @field_validator("base_url")
    @classmethod
    def endpoint_without_credentials(cls, value: str) -> str:
        return safe_endpoint(value)


class Oracle(StrictModel):
    phase: Literal["home", "editing", "running"]
    name: str
    duration: Duration
    quiet: bool
    seed: int
    screen_width: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    screen_height: Annotated[float, Field(gt=0, allow_inf_nan=False)]


class SyntheticTree(StrictModel):
    labels: list[str]
    omitted_labels: Count = 0


def sanitize_tree(labels: list[str], scenarios: list[Scenario]) -> SyntheticTree:
    allowed = {"FocusBench", "Make time to focus.", "Plan one session.", "New session",
               "Session name", "Duration", "Quiet mode", "On", "Off", "Start session",
               "Session started", "Quiet mode on", "Quiet mode off", "State file unavailable"}
    allowed.update(f"{duration} minutes" for duration in (5, 10, 15, 25, 50))
    allowed.update(f"{duration} min" for duration in (5, 10, 15, 25, 50))
    for scenario in scenarios:
        allowed.update(scenario.allowed_texts)
        allowed.add(scenario.initial.prefill)
    return SyntheticTree(labels=[label for label in labels if label in allowed],
                         omitted_labels=sum(label not in allowed for label in labels))


def initial_issues(oracle: Oracle, scenario: Scenario, seed: int,
                   screen: ScreenSize) -> list[str]:
    checks = {"phase": oracle.phase == "home", "name": oracle.name == scenario.initial.prefill,
              "duration": oracle.duration == scenario.initial.duration,
              "quiet": oracle.quiet == scenario.initial.quiet, "seed": oracle.seed == seed,
              "geometry": (oracle.screen_width == screen.width
                           and oracle.screen_height == screen.height)}
    return [f"initial_{field}_mismatch" for field, matches in checks.items() if not matches]


class Evaluation(StrictModel):
    oracle: Oracle | None
    tree: SyntheticTree | None
    issues: list[str]

    @property
    def passed(self) -> bool:
        return self.oracle is not None and self.tree is not None and not self.issues


def evaluate(scenario: Scenario, seed: int, screen: ScreenSize,
             oracle: Oracle | None, tree: SyntheticTree | None) -> Evaluation:
    issues: list[str] = []
    expected = scenario.expected
    if oracle is None:
        issues.append("final_oracle_unavailable")
    else:
        checks = {"phase": oracle.phase == expected.phase, "name": oracle.name == expected.name,
                  "duration": oracle.duration == expected.duration,
                  "quiet": oracle.quiet == expected.quiet, "seed": oracle.seed == seed,
                  "geometry": (oracle.screen_width == screen.width
                               and oracle.screen_height == screen.height)}
        issues.extend(f"final_{field}_mismatch" for field, match in checks.items() if not match)
    if tree is None:
        issues.append("final_tree_unavailable")
    else:
        required = {"started": "Session started", "name": expected.name,
                    "duration": f"{expected.duration} minutes",
                    "quiet": f"Quiet mode {'on' if expected.quiet else 'off'}"}
        issues.extend(f"visible_{field}_missing" for field, label in required.items()
                      if label not in tree.labels)
        wrong_quiet = f"Quiet mode {'off' if expected.quiet else 'on'}"
        if wrong_quiet in tree.labels or "State file unavailable" in tree.labels:
            issues.append("visible_conflicting_state")
    return Evaluation(oracle=oracle, tree=tree, issues=issues)


def report_issues(report: RunReport, config: ProviderConfig, exit_code: int | None) -> list[str]:
    issues: list[str] = []
    if exit_code != (0 if report.status == "completed" else 2):
        issues.append("report_exit_status_mismatch")
    if report.mode != config.mode:
        issues.append("report_mode_mismatch")
    if report.status == "completed" and (not report.calls or not report.calls[-1].succeeded):
        issues.append("report_completion_call_missing_or_failed")
    identities = [report.identity, *(call.identity for call in report.calls)]
    for identity in identities:
        if identity.name != config.provider or identity.requested_model != config.model:
            issues.append("report_identity_mismatch")
            break
    decision_endpoint = config.base_url + (
        "/v1/systemone" if config.provider == "winnow" else "/alpha/decisions")
    chat_endpoint = config.base_url + "/v1/chat/completions"
    final_endpoints = {chat_endpoint if config.mode == "direct" else decision_endpoint}
    if config.provider == "winnow" and not any(call.succeeded for call in report.calls):
        final_endpoints.add(decision_endpoint)  # Initial identity before a successful request.
    try:
        if (safe_endpoint(report.identity.endpoint) not in final_endpoints or any(
                safe_endpoint(call.identity.endpoint) != (
                    decision_endpoint if call.kind == "decision" else chat_endpoint)
                for call in report.calls)):
            issues.append("report_endpoint_mismatch")
    except ValueError:
        issues.append("report_endpoint_mismatch")
    counts = [report.steps, report.native_commands, report.native_mutations, report.native_failures,
              report.decision_requests, report.generative_requests, report.unpriced_requests]
    if (any(count < 0 for count in counts) or report.native_failures > report.native_commands
            or report.native_mutations > report.native_commands):
        issues.append("report_invalid_counts")
    if (report.steps > config.max_steps
            or report.decision_requests + report.generative_requests > config.max_requests):
        issues.append("report_budget_mismatch")
    if (report.decision_requests != sum(call.kind == "decision" for call in report.calls)
            or report.generative_requests != sum(
                call.kind == "generative" for call in report.calls)):
        issues.append("report_call_counts_mismatch")
    if not math.isclose(report.model_seconds,
                        sum(call.usage.request_ms for call in report.calls) / 1000, abs_tol=1e-6):
        issues.append("report_model_time_mismatch")
    if report.model_seconds > report.elapsed_seconds + 1e-6:
        issues.append("report_wall_time_mismatch")
    costs = [call.usage.reported_cost_usd for call in report.calls]
    known = [cost for cost in costs if cost is not None]
    if report.unpriced_requests != sum(cost is None for cost in costs):
        issues.append("report_unpriced_counts_mismatch")
    expected_cost = sum(known) if known else None
    if ((report.reported_cost_usd is None) != (expected_cost is None)
            or (report.reported_cost_usd is not None and expected_cost is not None
                and not math.isclose(report.reported_cost_usd, expected_cost, abs_tol=1e-9))):
        issues.append("report_cost_mismatch")
    return issues


class Proof(StrictModel):
    screenshot: str | None = None
    tree: str | None = None
    video: str | None = None


def saved_proof_issues(episode: Episode, directory: Path) -> list[str]:
    """Inspect bounded files without letting missing evidence discard an episode."""
    issues: list[str] = []
    for kind, reference in (("screenshot", episode.proof.screenshot),
                            ("tree", episode.proof.tree), ("video", episode.proof.video)):
        if reference is None:
            if kind != "video":
                issues.append(f"proof_{kind}_missing")
            continue
        try:
            relative = Path(reference)
            # Check both syntax and resolved containment, including symlink escapes.
            if (not reference or relative.is_absolute() or ".." in relative.parts
                    or "\\" in reference or ":" in reference):
                raise ValueError("unsafe_reference")
            path = (directory / relative).resolve()
            if not path.is_relative_to(directory.resolve()):
                raise ValueError("unsafe_reference")
            if not path.is_file() or path.stat().st_size == 0:
                issues.append(f"proof_{kind}_missing_or_empty")
                continue
            if kind == "screenshot":
                with Image.open(path) as image:
                    if image.format != "PNG":
                        raise ValueError("not_png")
                    image.verify()
            elif kind == "tree":
                tree = SyntheticTree.model_validate_json(path.read_bytes())
                if not tree.labels or tree != episode.evaluation.tree:
                    raise ValueError("tree_mismatch")
        except (OSError, RuntimeError, ValueError, Image.DecompressionBombError):
            issues.append(f"proof_{kind}_invalid")
    return ["proof_incomplete", *issues] if issues else []


class Episode(StrictModel):
    schema_version: Literal[1] = 1
    scenario: Scenario
    repetition: Count
    seed: int
    screen: ScreenSize
    provider_config: ProviderConfig
    report: RunReport | None
    exit_code: int | None
    evaluation: Evaluation
    setup_failures: list[str]
    proof_failures: list[str] = Field(default_factory=list)
    resources: ResourceReport | None = None
    proof: Proof = Field(default_factory=Proof)

    def issues(self) -> list[str]:
        issues = [*self.setup_failures, *self.proof_failures]
        if self.seed != self.scenario.initial.seed + 1009 * self.repetition:
            issues.append("episode_seed_mismatch")
        if self.report is None:
            issues.append("report_unavailable")
        else:
            issues.extend(report_issues(self.report, self.provider_config, self.exit_code))
            if self.report.status != "completed":
                issues.append("report_not_completed")
        checked = evaluate(self.scenario, self.seed, self.screen,
                           self.evaluation.oracle, self.evaluation.tree)
        if self.evaluation.issues != checked.issues:
            issues.append("evaluation_inconsistent")
        issues.extend(checked.issues)
        if not self.proof.screenshot or not self.proof.tree:
            issues.append("proof_incomplete")
        return issues


class Interval(StrictModel):
    low: Nonnegative
    high: Nonnegative


def wilson(successes: int, count: int) -> Interval:
    if not 0 <= successes <= count or count < 1:
        raise ValueError("Wilson interval requires 0 <= successes <= count and count > 0")
    z = 1.959963984540054
    fraction = successes / count
    denominator = 1 + z * z / count
    center = (fraction + z * z / (2 * count)) / denominator
    radius = z * math.sqrt(fraction * (1 - fraction) / count + z * z / (4 * count**2))
    return Interval(low=max(0.0, center - radius / denominator),
                    high=min(1.0, center + radius / denominator))


class Counts(StrictModel):
    episodes: Count
    successes: Count
    failures: Count
    independent_outcome_successes: Count
    saved_proof_complete: Count | None
    success_interval_95: Interval
    wall_seconds: Nonnegative
    model_seconds: Nonnegative
    reported_cost_usd: Nonnegative | None
    unpriced_requests: Count
    missing_reports: Count
    inconsistent_reports: Count
    steps: Count
    native_commands: Count
    native_mutations: Count
    native_failures: Count
    decision_requests: Count
    generative_requests: Count
    statuses: dict[str, int]
    failure_reasons: dict[str, int]


class Stratum(StrictModel):
    scenario: str
    provider_config: ProviderConfig
    screen: ScreenSize
    counts: Counts


class InvalidFile(StrictModel):
    file: str
    reason: Literal["invalid_episode", "duplicate_episode"]


class CoverageSlot(StrictModel):
    cell: str
    scenario: str
    repetition: Count


class Coverage(StrictModel):
    expected: Count = 105
    observed: Count
    matched: Count
    missing: list[CoverageSlot]
    unexpected: list[str]
    issues: list[str]

    @property
    def complete(self) -> bool:
        return self.matched == self.expected and not (
            self.missing or self.unexpected or self.issues)


class Summary(StrictModel):
    strata: list[Stratum]
    invalid_files: list[InvalidFile]
    coverage: Coverage | None = None
    caveat: str = ("Synthetic FocusBench tasks only. Quality, mode, and model are confounded; "
                   "these observations support no causal or general-app claims. Wilson intervals "
                   "treat episodes as independent; matched repeats may be correlated.")


def aggregate(episodes: list[Episode], *, proof_checked: bool = False) -> list[Stratum]:
    groups: dict[tuple[str, str, str], list[Episode]] = {}
    for episode in episodes:
        key = (episode.scenario.model_dump_json(), episode.provider_config.model_dump_json(),
               episode.screen.model_dump_json())
        groups.setdefault(key, []).append(episode)
    strata: list[Stratum] = []
    for rows in groups.values():
        reports = [row.report for row in rows if row.report is not None]
        failures: dict[str, int] = {}
        statuses: dict[str, int] = {}
        successes = 0
        inconsistent = 0
        for row in rows:
            issues = row.issues()
            successes += not issues
            inconsistent += bool(row.report and report_issues(
                row.report, row.provider_config, row.exit_code))
            status = row.report.status if row.report else "missing_report"
            statuses[status] = statuses.get(status, 0) + 1
            for issue in set(issues):
                failures[issue] = failures.get(issue, 0) + 1
        # Inconsistent reports remain failed episodes but do not contaminate numeric totals.
        usable = [row.report for row in rows if row.report is not None
                  and not report_issues(row.report, row.provider_config, row.exit_code)]
        known_costs = [report.reported_cost_usd for report in usable
                       if report.reported_cost_usd is not None]
        counts = Counts(episodes=len(rows), successes=successes, failures=len(rows) - successes,
                        independent_outcome_successes=sum(
                            evaluate(row.scenario, row.seed, row.screen,
                                     row.evaluation.oracle, row.evaluation.tree).passed
                            for row in rows),
                        saved_proof_complete=(sum(
                            not any(issue.startswith("proof_") for issue in row.issues())
                            for row in rows) if proof_checked else None),
                        success_interval_95=wilson(successes, len(rows)),
                        wall_seconds=sum(report.elapsed_seconds for report in usable),
                        model_seconds=sum(report.model_seconds for report in usable),
                        reported_cost_usd=sum(known_costs) if known_costs else None,
                        unpriced_requests=sum(report.unpriced_requests for report in usable),
                        missing_reports=len(rows) - len(reports), inconsistent_reports=inconsistent,
                        steps=sum(report.steps for report in usable),
                        native_commands=sum(report.native_commands for report in usable),
                        native_mutations=sum(report.native_mutations for report in usable),
                        native_failures=sum(report.native_failures for report in usable),
                        decision_requests=sum(report.decision_requests for report in usable),
                        generative_requests=sum(report.generative_requests for report in usable),
                        statuses=statuses, failure_reasons=failures)
        strata.append(Stratum(scenario=rows[0].scenario.id, provider_config=rows[0].provider_config,
                              screen=rows[0].screen, counts=counts))
    return sorted(strata, key=lambda item: (item.scenario, item.provider_config.model_dump_json(),
                                           item.screen.model_dump_json()))


def summarize(directory: Path, expected: Path | None = None) -> Summary:
    episodes: list[Episode] = []
    observed: list[tuple[Path, Episode]] = []
    invalid: list[InvalidFile] = []
    seen: set[tuple[str, int, str, str]] = set()
    for path in sorted(directory.rglob("episode.json")):
        try:
            episode = Episode.model_validate_json(path.read_bytes())
        except (OSError, ValidationError):
            invalid.append(InvalidFile(file=str(path.relative_to(directory)),
                                       reason="invalid_episode"))
            continue
        key = (episode.scenario.model_dump_json(), episode.repetition,
               episode.provider_config.model_dump_json(), episode.screen.model_dump_json())
        observed.append((path, episode))
        episode.proof_failures.extend(saved_proof_issues(episode, path.parent))
        if key in seen:
            invalid.append(InvalidFile(file=str(path.relative_to(directory)),
                                       reason="duplicate_episode"))
        else:
            episodes.append(episode)
            seen.add(key)
    coverage = None
    explicit_expected = expected is not None
    expected = expected or (directory / "expected-matrix.json")
    if explicit_expected or expected.exists():
        from benchmarks.matrix import check_coverage

        coverage = check_coverage(directory, observed, expected)
        if invalid:
            coverage.issues.append("invalid_episode_files")
    return Summary(strata=aggregate(episodes, proof_checked=True), invalid_files=invalid,
                   coverage=coverage)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--expected", type=Path, help="Frozen expected-matrix.json (105 episodes)")
    args = parser.parse_args()
    if args.expected is not None and not Path(args.expected).is_file():
        print("expected_matrix_unavailable")
        return 2
    summary = summarize(Path(args.directory), args.expected)
    output = summary.model_dump_json(indent=2)
    if args.output:
        Path(args.output).write_text(output + "\n")
    print(output)
    return 2 if (summary.invalid_files or not summary.strata
                 or (summary.coverage is not None and not summary.coverage.complete)) else 0


if __name__ == "__main__":
    raise SystemExit(main())
