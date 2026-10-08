"""Plot recorded synthetic inference latency without contacting a provider.

Run with ``uv run --no-sync --with matplotlib python -m benchmarks.plot_local``.
Matplotlib is an optional plotting tool, not a library runtime dependency.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.ticker import LogLocator, NullLocator, ScalarFormatter
from pydantic import ValidationError

from .inference import Report, Series, cache_issues, summarize


class Arguments(argparse.Namespace):
    input: Path
    output_dir: Path
    linear: bool


def load_report(path: Path) -> Report:
    """Reject incomplete or inconsistent evidence rather than plot a valid subset."""
    report = Report.model_validate_json(path.read_bytes())
    case_ids = {case.case_id for case in report.cases}
    if not case_ids or len(case_ids) != len(report.cases):
        raise ValueError("Report needs nonempty, unique cases")
    sample_ids = {sample.sample_id for sample in report.samples}
    if len(sample_ids) != len(report.samples):
        raise ValueError("Duplicate sample IDs would inflate the denominator")
    if any(sample.case_id not in case_ids for sample in report.samples):
        raise ValueError("Sample refers to an unknown case")
    failures = sum(not sample.answers_valid or bool(sample.issues) for sample in report.samples)
    if failures:
        raise ValueError(
            f"Refusing a selected latency chart: {failures}/{len(report.samples)} "
            "attempts failed, including setup"
        )
    for sample in report.samples:
        if cache_issues(sample.stage, sample.native):
            raise ValueError(f"Cache regime unverified for sample {sample.sample_id}")
        if sample.reuse_prefix != (sample.stage != "cold"):
            raise ValueError(f"Prefix policy inconsistent for sample {sample.sample_id}")
    for case in report.cases:
        for stage, expected in (("cold", report.config.repeats), ("setup", 1),
                                ("warm", report.config.repeats)):
            rows = [s for s in report.samples if s.case_id == case.case_id and s.stage == stage]
            if len(rows) != expected or {s.repetition for s in rows} != set(range(expected)):
                raise ValueError(f"Incomplete repetition coverage: {case.name}/{stage}")
            if any(s.submitted_questions != case.questions for s in rows):
                raise ValueError(f"Question count inconsistent for {case.name}/{stage}")
    if report.series != summarize(report.samples, report.cases):
        raise ValueError("Saved summaries differ from the raw attempts")
    if not all(series.regime_verified for series in report.series):
        raise ValueError("Every plotted regime must be verified; no subset selection")
    return report


def plot_series(axes: Axes, series: Series, row: float, color: str, marker: str) -> None:
    timing = series.latency["wall_ms"]
    median = timing.median / 1000
    minimum = timing.minimum / 1000
    maximum = timing.maximum / 1000
    axes.errorbar(
        median, row, xerr=[[median - minimum], [maximum - median]],
        fmt=marker, color=color, markersize=6, capsize=4, elinewidth=1.5,
    )
    axes.annotate(
        f"{median:.3f} s", xy=(median, row), xytext=(0, 7 if series.stage == "cold" else -14),
        textcoords="offset points", ha="center", fontsize=9, color=color,
    )


def render(report: Report, output_dir: Path, linear: bool = False) -> tuple[Path, Path]:
    """Render all measured attempts; setup stays in the reported denominator."""
    timings = [series.latency["wall_ms"] for series in report.series]
    minimum = min(timing.minimum for timing in timings) / 1000
    maximum = max(timing.maximum for timing in timings) / 1000
    if not linear and minimum <= 0:
        raise ValueError("Log latency requires positive observations; use --linear for zero")
    figure = Figure(figsize=(14, 8), facecolor="white")
    axes = figure.add_subplot(111)
    figure.subplots_adjust(left=0.28, right=0.80, top=0.77, bottom=0.27)
    colors = {"cold": "#0072B2", "warm": "#D55E00"}
    markers = {"cold": "o", "warm": "D"}
    offsets = {"cold": -0.16, "warm": 0.16}
    labels: list[str] = []
    for index, case in enumerate(report.cases):
        image = (f"{case.image_width} x {case.image_height} px"
                 if case.image_width else "none")
        labels.append(f"{case.name}\n{case.questions} questions; image {image}")
        if index % 2 == 0:
            axes.axhspan(index - 0.48, index + 0.48, color="#f3f5f7", zorder=0)
        series_rows = [series for series in report.series if series.case_id == case.case_id]
        counts: list[str] = []
        for series in series_rows:
            plot_series(axes, series, index + offsets[series.stage],
                        colors[series.stage], markers[series.stage])
            counts.append(f"{series.valid_samples}/{series.attempts}; {series.failures} failed")
        axes.text(1.04, index, "C: " + counts[0] + "\nW: " + counts[1],
                  transform=axes.get_yaxis_transform(), va="center", fontsize=9, color="#333333")
    axes.set_yticks(range(len(labels)), labels=labels, fontsize=10)
    axes.set_ylim(len(labels) - 0.45, -0.75)
    axes.tick_params(axis="y", length=0, pad=12)
    if linear:
        axes.set_xlim(0, maximum * 1.5)
    else:
        axes.set_xscale("log")
        axes.set_xlim(minimum * 0.8, maximum * 1.5)
        axes.xaxis.set_major_locator(LogLocator(base=10, subs=(1, 2, 5)))
        axes.xaxis.set_minor_locator(NullLocator())
        formatter = ScalarFormatter()
        formatter.set_scientific(False)
        formatter.set_useOffset(False)
        axes.xaxis.set_major_formatter(formatter)
    axes.set_xlabel("Client wall latency (seconds" + (", log scale)" if not linear else ")"),
                    fontsize=11, labelpad=10)
    axes.grid(axis="x", color="#d5d9df", linewidth=0.7)
    axes.set_axisbelow(True)
    for side in ("top", "right", "left"):
        axes.spines[side].set_visible(False)

    first_cold = next(sample for sample in report.samples if sample.stage == "cold")
    first_index = next(i for i, case in enumerate(report.cases)
                       if case.case_id == first_cold.case_id)
    axes.annotate(
        f"First prefix-cold: {first_cold.wall_ms / 1000:.2f} s (retained)",
        xy=(first_cold.wall_ms / 1000, first_index + offsets["cold"]),
        xytext=(-165, 25), textcoords="offset points", fontsize=9, color=colors["cold"],
        arrowprops={"arrowstyle": "->", "color": colors["cold"], "linewidth": 0.8},
    )
    figure.text(0.28, 0.95, f"{report.config.model}: recorded local inference latency",
                fontsize=17, weight="bold")
    memory = report.host.physical_memory_bytes
    ram = f"{memory / 2**30:g} GiB" if memory is not None else "RAM unreported"
    launch = report.config.launch
    host = report.host.cpu_model or "Host unreported"
    figure.text(0.28, 0.91,
                f"{host}, {ram} | {launch.quantization or 'quantization unreported'} | "
                f"ctx {launch.context_capacity or 'unreported'} | "
                f"{launch.kv_cache or 'unreported'} KV (operator declarations)", fontsize=10)
    figure.legend(
        handles=[Line2D([], [], color=colors[stage], marker=markers[stage], linestyle="none",
                        label=f"{label} ({report.config.repeats} samples per regime)")
                 for stage, label in (("cold", "Prefix-cold"), ("warm", "Verified cached warm"))],
        loc="upper left", bbox_to_anchor=(0.272, 0.883), frameon=False, ncols=2, fontsize=10,
    )
    figure.text(0.28, 0.81, "Markers: medians. Capped bars: min/max, not confidence intervals.",
                fontsize=10)
    setup = sum(sample.stage == "setup" for sample in report.samples)
    measured = len(report.samples) - setup
    cold = sum(sample.stage == "cold" for sample in report.samples)
    warm = sum(sample.stage == "warm" for sample in report.samples)
    notes = (
        f"{len(report.samples)} attempts = {measured} measured + {setup} setup "
        "(setup excluded from latency).\n"
        f"Failures: 0/{len(report.samples)} total; cold 0/{cold}, warm 0/{warm}, setup 0/{setup}. "
        "Right: valid/attempts, failed counts.\n"
        "Prefix-cold disables prefix reuse; "
        "it does not mean model-start or filesystem-cache cold.\n"
        "Warm: every sample has cache_hit=true and prefix_reused_tokens>0. "
        f"{report.config.repeats} samples do not establish tail latency.\n"
        f"Recorded {report.created_utc}; synthetic sequential workloads only. "
        "Unreported prices remain unknown."
    )
    figure.text(0.28, 0.17, notes, fontsize=9, linespacing=1.6, va="top", color="#333333")
    output_dir.mkdir(parents=True, exist_ok=True)
    png = output_dir / "latency.png"
    svg = output_dir / "latency.svg"
    figure.savefig(png, dpi=180, facecolor="white")
    figure.savefig(svg, facecolor="white")
    return png, svg


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path,
                        default=Path("results/local-performance/results.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("results/local-performance"))
    parser.add_argument("--linear", action="store_true", help="Use a linear latency axis")
    args = Arguments()
    parser.parse_args(namespace=args)
    try:
        report = load_report(args.input)
        png, svg = render(report, args.output_dir, args.linear)
    except (OSError, ValueError, ValidationError) as error:
        parser.exit(2, f"Plot rejected: {error}\n")
    print(f"Validated {len(report.samples)} attempts; wrote {png} and {svg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
