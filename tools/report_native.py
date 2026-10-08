"""Build an offline report from a complete, frozen native benchmark matrix.

Run from the checkout with optional Matplotlib: uv run --no-sync --with
matplotlib python -m tools.report_native --input MATRIX --output-dir RESULTS.
This reporting tool is outside the frozen planner/benchmark implementation.
"""

from __future__ import annotations

import argparse
import hashlib
import statistics
from collections import Counter
from pathlib import Path
from typing import Literal

from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from pydantic import Field, ValidationError

from axe_control.decisions import Count, Nonnegative, StrictModel
from axe_control.models import ScreenSize
from benchmarks.matrix import ExpectedMatrix, MatrixRun, Snapshot
from benchmarks.summarize import Episode, Summary, evaluate, summarize


class CellMeasurements(StrictModel):
    cell: str
    model: str
    mode: str
    episodes: Count
    passed: Count
    outcomes_reached: Count
    passed_by_scenario: dict[str, int]
    all_wall_median_seconds: Nonnegative
    successful_wall_median_seconds: Nonnegative | None
    failed_wall_median_seconds: Nonnegative | None
    model_seconds: Nonnegative
    steps: Count
    requests: Count
    native_commands: Count
    native_mutations: Count
    native_failures: Count
    reported_cost_usd: Nonnegative | None
    unpriced_requests: Count
    stop_reasons: dict[str, int]
    resolved_models: list[str]
    resolved_providers: list[str]
    unresolved_calls: Count
    resource_samples: Count
    resource_errors: list[str]
    sampled_peak_process_rss_kib: Count | None
    sampled_peak_process_cpu_percent: Nonnegative | None
    backend_allocated_min_bytes: Count | None
    backend_allocated_max_bytes: Count | None
    wall_samples_seconds: list[Nonnegative]
    passed_samples: list[bool]


class Measurements(StrictModel):
    schema_version: Literal[1] = 1
    expected_sha256: str
    implementation_fingerprint: str
    started_utc: str
    finished_utc: str
    screen: ScreenSize
    max_seconds: Count
    max_steps: Count
    max_requests: Count
    runtime: Snapshot
    scenarios: list[str]
    saved_proof_complete: Count
    cells: list[CellMeasurements] = Field(min_length=7, max_length=7)
    caveat: str


def load(directory: Path) -> tuple[Measurements, Summary]:
    expected_bytes = (directory / "expected-matrix.json").read_bytes()
    expected = ExpectedMatrix.model_validate_json(expected_bytes)
    ledger = MatrixRun.model_validate_json((directory / "matrix-run.json").read_bytes())
    summary = summarize(directory)
    if (summary.invalid_files or summary.coverage is None or not summary.coverage.complete
            or ledger.finished_utc is None):
        raise ValueError("Refusing a partial, changed or invalid matrix")
    if any(row.counts.missing_reports or row.counts.inconsistent_reports
           for row in summary.strata):
        raise ValueError("Every attempted episode must have a consistent report")
    proof = sum(row.counts.saved_proof_complete or 0 for row in summary.strata)
    if proof != 105:
        raise ValueError("Every episode needs valid saved proof, including failures")
    if ledger.expected_sha256 != hashlib.sha256(expected_bytes).hexdigest():
        raise ValueError("Ledger does not match the frozen expectation")
    episodes = [Episode.model_validate_json(path.read_bytes())
                for path in sorted(directory.rglob("episode.json"))]
    cells: list[CellMeasurements] = []
    scenarios = [row.id for row in expected.scenarios]
    for cell in expected.cells:
        rows = [row for row in episodes if row.provider_config == cell.config]
        reports = [row.report for row in rows if row.report is not None]
        if len(rows) != 15 or len(reports) != 15:
            raise ValueError("Each cell needs all fifteen attempted reports")
        passed = [not row.issues() for row in rows]
        successful = [report.elapsed_seconds for report, ok in zip(reports, passed, strict=True)
                      if ok]
        failed = [report.elapsed_seconds for report, ok in zip(reports, passed, strict=True)
                  if not ok]
        calls = [call for report in reports for call in report.calls]
        resources = [row.resources for row in rows if row.resources is not None]
        samples = [sample for resource in resources for sample in resource.samples]
        allocated = [call.usage.backend_allocated_bytes for call in calls
                     if call.usage.backend_allocated_bytes is not None]
        costs = [report.reported_cost_usd for report in reports
                 if report.reported_cost_usd is not None]
        counts = [row.counts for row in summary.strata if row.provider_config == cell.config]
        if sum(passed) != sum(row.successes for row in counts):
            raise ValueError("Saved proof audit and episode pass counts disagree")
        cells.append(CellMeasurements(
            cell=cell.id, model=cell.config.model, mode=cell.config.mode,
            episodes=len(rows), passed=sum(passed), outcomes_reached=sum(
                evaluate(row.scenario, row.seed, row.screen, row.evaluation.oracle,
                         row.evaluation.tree).passed for row in rows),
            passed_by_scenario={scenario:sum(not row.issues() for row in rows
                                           if row.scenario.id == scenario)
                                for scenario in scenarios},
            all_wall_median_seconds=statistics.median(r.elapsed_seconds for r in reports),
            successful_wall_median_seconds=statistics.median(successful) if successful else None,
            failed_wall_median_seconds=statistics.median(failed) if failed else None,
            model_seconds=sum(r.model_seconds for r in reports),
            steps=sum(r.steps for r in reports),
            requests=sum(r.decision_requests + r.generative_requests for r in reports),
            native_commands=sum(r.native_commands for r in reports),
            native_mutations=sum(r.native_mutations for r in reports),
            native_failures=sum(r.native_failures for r in reports),
            reported_cost_usd=sum(costs) if costs else None,
            unpriced_requests=sum(r.unpriced_requests for r in reports),
            stop_reasons=dict(Counter(r.reason for r in reports if r.status != "completed")),
            resolved_models=sorted({c.identity.resolved_model for c in calls
                                    if c.identity.resolved_model is not None}),
            resolved_providers=sorted({c.identity.resolved_provider for c in calls
                                       if c.identity.resolved_provider is not None}),
            unresolved_calls=sum(c.identity.resolved_model is None for c in calls),
            resource_samples=len(samples),
            resource_errors=sorted({error for resource in resources for error in resource.errors}),
            sampled_peak_process_rss_kib=max((s.rss_kib for s in samples), default=None),
            sampled_peak_process_cpu_percent=max((s.cpu_percent for s in samples), default=None),
            backend_allocated_min_bytes=min(allocated, default=None),
            backend_allocated_max_bytes=max(allocated, default=None),
            wall_samples_seconds=[r.elapsed_seconds for r in reports], passed_samples=passed,
        ))
    return Measurements(
        expected_sha256=ledger.expected_sha256,
        implementation_fingerprint=expected.frozen.fingerprint(),
        started_utc=ledger.started_utc, finished_utc=ledger.finished_utc,
        screen=expected.screen,
        max_seconds=expected.cells[0].config.max_seconds,
        max_steps=expected.cells[0].config.max_steps,
        max_requests=expected.cells[0].config.max_requests,
        runtime=expected.frozen,
        scenarios=scenarios, saved_proof_complete=proof, cells=cells, caveat=summary.caveat,
    ), summary


def timing(value: float | None) -> str:
    return f"{value:.3f}" if value is not None else "not available"


def markdown(report: Measurements) -> str:
    lines = [
        "# Native controller benchmark", "",
        "All **105 episodes** are retained: seven compatible model/mode cells, five",
        "seeded synthetic scenarios, three matched repetitions. Every episode has",
        "validated saved screenshot/tree proof and a consistent controller report.", "",
        f"Started `{report.started_utc}`; finished `{report.finished_utc}`.",
        f"Frozen implementation fingerprint: `{report.implementation_fingerprint}`.", "",
        f"Declared simulator runtime: `{report.runtime.simulator_runtime}`. Logical screen: "
        f"{report.screen.width:g} × {report.screen.height:g} points. Screenshot pixels are "
        "a separate unit; no universal display scale is assumed.", "",
        f"Every cell uses {report.max_steps} steps, {report.max_requests} model requests "
        f"and a cooperative {report.max_seconds}-second budget. In-flight requests may "
        "finish after that budget. Each scenario uses the same three seeded repetitions.", "",
        f"Client: Python {report.runtime.python}; {report.runtime.system}, "
        f"{report.runtime.machine}. Package versions: "
        + ", ".join(f"{name} {value}" for name, value in sorted(report.runtime.packages.items()))
        + ".", "",
        f"Source hash `{report.runtime.source_sha256}`; imported package hash "
        f"`{report.runtime.runtime_package_sha256}`; fixture hash "
        f"`{report.runtime.fixture_sha256}`. Before/after cell snapshots match the "
        "frozen expectation; this does not prove an external provider stayed unchanged.", "",
        "A **pass** requires controller completion, independent fixture oracle plus",
        "visible final facts, valid report/exit accounting and saved proof.",
        "**Outcome reached** counts the independent native result even when the",
        "controller refused completion. These denominators must not be conflated.", "",
        "![Native outcomes](outcomes.png)", "",
        "![All attempted controller wall times](latency.png)", "",
        "Wall time excludes app setup and video encoding. Both failed and passing",
        "attempts are shown; a fast refusal is not fast task completion. Successful",
        "medians condition on success and need their smaller sample counts.", "",
    ]
    for title, cells in (("Hosted", report.cells[:4]), ("Local Winnow", report.cells[4:])):
        lines += [f"## {title}", "",
                  "| Cell | Pass / attempts | Outcome reached | All wall median, s | "
                  "Passing wall median, s |",
                  "| --- | --- | --- | --- | --- |"]
        for cell in cells:
            lines.append(f"| {cell.cell} | {cell.passed}/{cell.episodes} | "
                         f"{cell.outcomes_reached}/{cell.episodes} | "
                         f"{timing(cell.all_wall_median_seconds)} | "
                         f"{timing(cell.successful_wall_median_seconds)} (n={cell.passed}) |")
        lines.append("")
    lines += ["## Scenario breakdown", "", "Each entry is passing episodes / 3 attempts.", ""]
    lines += ["| Scenario | " + " | ".join(c.cell for c in report.cells) + " |",
              "| --- | " + " | ".join("---" for _ in report.cells) + " |"]
    for scenario in report.scenarios:
        lines.append("| " + scenario + " | " + " | ".join(
            f"{c.passed_by_scenario[scenario]}/3" for c in report.cells) + " |")
    lines += ["", "## Requests, native work and reported charges", "",
              "Totals include passing and failed attempts. Requests are actual HTTP attempts;",
              "native commands include observations and execution; mutations count actual",
              "AXe operations. A missing reported price stays unknown.", ""]
    for cell in report.cells:
        cost = (f"${cell.reported_cost_usd:.8f} reported subtotal"
                if cell.reported_cost_usd is not None else "unknown reported cost")
        lines += [f"### {cell.cell}", "",
                  f"Requested `{cell.model}`; mode `{cell.mode}`. "
                  f"Resolved models: {', '.join(cell.resolved_models) or 'unknown'}. "
                  f"Resolved providers: {', '.join(cell.resolved_providers) or 'unreported'}.", "",
                  f"{cell.steps} planner steps; {cell.requests} requests; "
                  f"{cell.native_commands} native commands; {cell.native_mutations} mutations; "
                  f"{cell.native_failures} native failures; {cell.model_seconds:.3f} s "
                  f"total client model-request time. {cost}; "
                  f"{cell.unpriced_requests} unpriced requests. "
                  f"{cell.unresolved_calls} calls without resolved model identity.", "",
                  f"Failed-attempt wall median: {timing(cell.failed_wall_median_seconds)} s. "
                  f"Stop reasons: {cell.stop_reasons or 'none'}.", ""]
        if cell.resource_samples:
            rss = cell.sampled_peak_process_rss_kib
            lines += [f"{cell.resource_samples} whole-process samples; peak observed RSS "
                      f"{rss} KiB ({rss / 2**20:.3f} GiB)" if rss is not None else
                      "Process RSS unreported."]
            lines += [f"Peak sampled ps CPU {cell.sampled_peak_process_cpu_percent}%; "
                      f"sampling errors: {cell.resource_errors or 'none'}. Backend allocation "
                      f"range: {cell.backend_allocated_min_bytes}–"
                      f"{cell.backend_allocated_max_bytes} bytes.", ""]
        lines += [f"[First original recording]({cell.cell}/basic/repeat-0/original.mp4) · "
                  f"[Fresh final still]({cell.cell}/basic/repeat-0/final.png) · "
                  f"[Episode]({cell.cell}/basic/repeat-0/episode.json). "
                  "This is the first attempt, whether it passed or failed.", ""]
    lines += ["## Limits", "", report.caveat, "",
              "The local cells share an owned resident server. Background presentation",
              "captures, package builds and media checks occurred during the comparison;",
              "the host had swap in use. Their per-episode contribution was not isolated.",
              "Sampled process RSS and backend/device allocation",
              "are distinct accounting views, never summed or labeled per-request peaks.",
              "CPU is ps utilization, not energy. Three repeats do not establish stable tails,",
              "production reliability or calibrated model beliefs. Hosted errors remain in",
              "the failure denominator. Jev is text-only; "
              "Clef/Jev chat baselines are unsupported.", "",
              "Recordings retain original native timestamps; no fixed recording FPS is claimed.",
              "For per-scenario request/cost/failure counts and qualified Wilson intervals see",
              "[summary.json](summary.json); for plot inputs see "
              "[measurements.json](measurements.json).", ""]
    return "\n".join(lines)


def render(report: Measurements, output: Path) -> None:
    labels = [f"{cell.model}\n{cell.mode}" for cell in report.cells]
    figure = Figure(figsize=(13, 7), facecolor="white")
    axes = figure.add_subplot(111)
    figure.subplots_adjust(left=0.26, right=0.91, top=0.78, bottom=0.20)
    for index, cell in enumerate(report.cells):
        axes.barh(index - 0.16, cell.passed, height=0.28, color="#0072B2")
        axes.barh(index + 0.16, cell.outcomes_reached, height=0.28, color="#E69F00")
        axes.text(cell.passed + 0.15, index - 0.16, f"{cell.passed}/15", va="center", fontsize=10)
        axes.text(cell.outcomes_reached + 0.15, index + 0.16,
                  f"{cell.outcomes_reached}/15", va="center", fontsize=10)
    axes.set_yticks(range(7), labels=labels, fontsize=10)
    axes.invert_yaxis()
    axes.set_xlim(0, 16.5)
    axes.set_xticks([0, 3, 6, 9, 12, 15])
    axes.set_xlabel("Episodes / 15 attempted in each cell")
    axes.grid(axis="x", alpha=0.25)
    axes.set_axisbelow(True)
    axes.legend(handles=[Line2D([0], [0], color="#0072B2", linewidth=8,
                               label="Controller + independent outcome + proof pass"),
                         Line2D([0], [0], color="#E69F00", linewidth=8,
                                label="Independent native outcome reached")],
                loc="upper left", bbox_to_anchor=(0, 1.17), frameon=False, fontsize=10)
    figure.text(0.26, 0.94, "Recorded native outcomes, including failed attempts",
                fontsize=17, weight="bold")
    figure.text(0.26, 0.89, "Five synthetic scenarios × three matched seeds; 105 proof sets valid",
                fontsize=11)
    figure.text(0.26, 0.08,
                "Model, mode and hosted/local execution differ. "
                "These counts are not general accuracy.\n"
                "A native outcome can be correct while the controller "
                "refuses its completion judgment.",
                fontsize=10)
    for extension in ("png", "svg"):
        figure.savefig(output / f"outcomes.{extension}", dpi=180)

    figure = Figure(figsize=(13, 7), facecolor="white")
    axes = figure.add_subplot(111)
    figure.subplots_adjust(left=0.26, right=0.94, top=0.78, bottom=0.20)
    for index, cell in enumerate(report.cells):
        for sample_index, (seconds, passed) in enumerate(zip(
                cell.wall_samples_seconds, cell.passed_samples, strict=True)):
            offset = (sample_index % 5 - 2) * 0.06
            axes.scatter(seconds, index + offset, marker="o" if passed else "x",
                         color="#0072B2" if passed else "#D55E00", s=34, alpha=0.8)
        axes.plot([cell.all_wall_median_seconds] * 2, [index - 0.28, index + 0.28],
                  color="#222222", linewidth=2)
    axes.set_yticks(range(7), labels=labels, fontsize=10)
    axes.invert_yaxis()
    axes.set_xlim(left=0)
    axes.set_xlabel("Controller wall time, seconds; excludes app setup and encoding")
    axes.grid(axis="x", alpha=0.25)
    axes.set_axisbelow(True)
    axes.legend(handles=[Line2D([0], [0], marker="o", linestyle="", color="#0072B2",
                               label="Passing attempt"),
                         Line2D([0], [0], marker="x", linestyle="", color="#D55E00",
                                label="Failed or blocked attempt"),
                         Line2D([0], [0], color="#222222", label="All-attempt median")],
                loc="upper left", bbox_to_anchor=(0, 1.14), frameon=False, ncols=3)
    figure.text(0.26, 0.94, "Every attempted native controller wall time",
                fontsize=17, weight="bold")
    figure.text(0.26, 0.88, "n=15 per cell; failures are retained, "
                "never plotted as successful completion",
                fontsize=11)
    figure.text(0.26, 0.08, "Fast failure is not fast task completion. "
                "No causal mode-only speed claim.\n"
                "The report separates all, passing and failed wall "
                "medians with actual denominators.",
                fontsize=10)
    for extension in ("png", "svg"):
        figure.savefig(output / f"latency.{extension}", dpi=180)


class Arguments(argparse.Namespace):
    input: Path
    output_dir: Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args(namespace=Arguments())
    try:
        report, summary = load(arguments.input)
        arguments.output_dir.mkdir(parents=True, exist_ok=True)
        (arguments.output_dir / "measurements.json").write_text(
            report.model_dump_json(indent=2) + "\n")
        (arguments.output_dir / "summary.json").write_text(summary.model_dump_json(indent=2) + "\n")
        (arguments.output_dir / "report.md").write_text(markdown(report))
        render(report, arguments.output_dir)
    except (OSError, ValueError, ValidationError):
        parser.exit(2, "Native report needs a complete consistent matrix and writable output.\n")
    print("Native report and plots saved from all 105 attempts; no provider/native calls.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
