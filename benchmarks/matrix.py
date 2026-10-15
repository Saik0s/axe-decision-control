#!/usr/bin/env python3
"""Freeze and sequentially run the seven-cell, 105-episode FocusBench matrix."""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Annotated, Literal, NoReturn, Self
from uuid import UUID

from pydantic import Field, TypeAdapter, model_validator

import axe_control
from axe_control.decisions import Nonnegative, StrictModel
from axe_control.models import ScreenSize

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmarks.summarize import (
    Coverage,
    CoverageSlot,
    Episode,
    ProviderConfig,
    Scenario,
    load_manifest,
    summarize,
)

ROOT = Path(__file__).resolve().parent.parent
SCENARIOS = ("basic", "duration", "quiet-off", "prefilled", "scroll")
CellID = Literal["gpt-direct", "clef-tree", "clef-grid", "jev-tree",
                 "winnow-direct", "winnow-tree", "winnow-grid"]
CELL_IDS: tuple[CellID, ...] = ("gpt-direct", "clef-tree", "clef-grid", "jev-tree",
                              "winnow-direct", "winnow-tree", "winnow-grid")
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Label = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9 ._()+-]{0,127}$")]
WinnowModel = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")]


class Cell(StrictModel):
    id: CellID
    config: ProviderConfig


def cells(winnow_model: str, winnow_url: str, openrouter_url: str,
          max_seconds: int, max_steps: int, max_requests: int) -> list[Cell]:
    return [Cell(id=identifier, config=ProviderConfig(
        provider="winnow" if identifier.startswith("winnow") else "openrouter",
        model=(winnow_model if identifier.startswith("winnow") else {
            "gpt": "openai/gpt-4.1-mini", "clef": "cloudflare/clef",
            "jev": "typesafe/jev-1.13"}[identifier.split("-")[0]]),
        mode="direct" if identifier.endswith("direct") else (
            "grid" if identifier.endswith("grid") else "tree"),
        base_url=winnow_url if identifier.startswith("winnow") else openrouter_url,
        max_seconds=max_seconds, max_steps=max_steps, max_requests=max_requests,
    )) for identifier in CELL_IDS]


class Snapshot(StrictModel):
    source_sha256: Digest
    runtime_package_sha256: Digest
    fixture_sha256: Digest
    python: str
    system: str
    machine: str
    packages: dict[str, str]
    simulator_runtime: Label

    def fingerprint(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


def files_digest(paths: list[Path], root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        file_hash = hashlib.sha256()
        with path.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                file_hash.update(block)
        digest.update(file_hash.digest())
    return digest.hexdigest()


def snapshot(app: Path, runtime: str) -> Snapshot:
    # Only hashes and runtime facts are persisted, never paths or environment values.
    sources = [*ROOT.joinpath("src").rglob("*.py"),
               *ROOT.joinpath("benchmarks").glob("*.py"),
               *ROOT.joinpath("fixtures").rglob("*.swift"),
               ROOT / "pyproject.toml", ROOT / "uv.lock", ROOT / "benchmarks/scenarios.json"]
    packages: dict[str, str] = {}
    for package in ("axe-decision-control", "httpx", "pydantic", "Pillow"):
        try:
            packages[package] = version(package)
        except PackageNotFoundError:
            packages[package] = "unavailable"
    fixture_files = [path for path in app.rglob("*") if path.is_file()]
    if not fixture_files:
        raise ValueError("fixture_unavailable")
    package_root = Path(axe_control.__file__).resolve().parent
    return Snapshot(source_sha256=files_digest(sources, ROOT),
                    runtime_package_sha256=files_digest(list(package_root.rglob("*.py")),
                                                        package_root),
                    fixture_sha256=files_digest(fixture_files, app),
                    python=platform.python_version(), system=platform.system(),
                    machine=platform.machine(), packages=packages, simulator_runtime=runtime)


class ExpectedMatrix(StrictModel):
    schema_version: Literal[1] = 1
    repeats: Literal[3] = 3
    screen: ScreenSize
    scenarios: list[Scenario]
    cells: list[Cell]
    frozen: Snapshot

    @model_validator(mode="after")
    def final_matrix(self) -> Self:
        if (len(self.scenarios) != 5 or {item.id for item in self.scenarios} != set(SCENARIOS)
                or tuple(item.id for item in self.cells) != CELL_IDS):
            raise ValueError("Expected exactly seven cells, five scenarios and three repeats")
        local = self.cells[4].config
        TypeAdapter(WinnowModel).validate_python(local.model, strict=True)
        # Regenerate the valid pairs; edited models, modes, endpoints or budgets fail closed.
        valid = cells(local.model, local.base_url, self.cells[0].config.base_url,
                      local.max_seconds, local.max_steps, local.max_requests)
        if self.cells != valid:
            raise ValueError("Invalid or unmatched matrix cells")
        return self


class CellResult(StrictModel):
    cell: CellID
    status: Literal["pending", "running", "finished", "failed", "cancelled"] = "pending"
    exit_code: int | None = None
    before: Digest | None = None
    after: Digest | None = None
    elapsed_seconds: Nonnegative = 0.0
    issues: list[str] = Field(default_factory=list)


class MatrixRun(StrictModel):
    schema_version: Literal[1] = 1
    expected_sha256: Digest
    started_utc: str
    finished_utc: str | None = None
    cells: list[CellResult]


def check_coverage(directory: Path, observed: list[tuple[Path, Episode]],
                   expected_path: Path) -> Coverage:
    try:
        raw = expected_path.read_bytes()
        expected = ExpectedMatrix.model_validate_json(raw)
    except (OSError, ValueError):
        return Coverage(observed=len(observed), matched=0, missing=[], unexpected=[],
                        issues=["invalid_expected_matrix"])
    slots = {(cell.id, scenario.id, repetition): CoverageSlot(
        cell=cell.id, scenario=scenario.id, repetition=repetition)
        for cell in expected.cells for scenario in expected.scenarios for repetition in range(3)}
    matched: dict[tuple[str, str, int], Episode] = {}
    unexpected: list[str] = []
    for path, episode in observed:
        relative = path.relative_to(directory)
        cell = next((item for item in expected.cells if item.id == relative.parts[0]), None)
        scenario = next((item for item in expected.scenarios if item == episode.scenario), None)
        key = (cell.id if cell else "", episode.scenario.id, episode.repetition)
        if (cell is None or scenario is None or key not in slots
                or cell.config != episode.provider_config or episode.screen != expected.screen
                or relative != Path(cell.id) / scenario.id / f"repeat-{episode.repetition}"
                / "episode.json" or key in matched):
            unexpected.append(relative.as_posix())
        else:
            matched[key] = episode
    issues: list[str] = []
    try:
        record = MatrixRun.model_validate_json((directory / "matrix-run.json").read_bytes())
        if record.expected_sha256 != hashlib.sha256(raw).hexdigest():
            issues.append("expected_matrix_changed")
        if tuple(item.cell for item in record.cells) != CELL_IDS:
            issues.append("matrix_run_cells_mismatch")
        if record.finished_utc is None:
            issues.append("matrix_run_unfinished")
        frozen = expected.frozen.fingerprint()
        for item in record.cells:
            if item.status not in {"finished", "failed"}:
                issues.append("matrix_cell_unfinished")
            if item.issues:
                issues.append("matrix_cell_harness_failure")
            if (item.status == "finished" and item.exit_code != 0
                    or item.status == "failed" and item.exit_code != 2):
                issues.append("matrix_cell_exit_status_mismatch")
            episodes = [episode for (cell, _, _), episode in matched.items() if cell == item.cell]
            failed = any(episode.issues() for episode in episodes)
            complete = len(episodes) == len(expected.scenarios) * 3
            # A known failure forces exit 2. Success needs every expected attempt;
            # missing attempts alone cannot contradict a quality-failed child.
            if not item.issues and item.status in {"finished", "failed"} and (failed or complete):
                if (item.status != ("failed" if failed else "finished")
                        or item.exit_code != (2 if failed else 0)):
                    issues.append("matrix_cell_episode_status_mismatch")
            if item.before != frozen or item.after != frozen:
                issues.append("implementation_or_runtime_changed")
    except (OSError, ValueError):
        issues.append("matrix_run_unavailable_or_invalid")
    return Coverage(observed=len(observed), matched=len(matched),
                    missing=[slot for key, slot in slots.items() if key not in matched],
                    unexpected=unexpected, issues=sorted(set(issues)))


def child_arguments(options: Options, cell: Cell, output: Path) -> list[str]:
    config = cell.config
    arguments = [sys.executable, "-m", "benchmarks.run", "--udid", options.udid,
                 "--app", str(options.app.resolve()), "--provider", config.provider,
                 "--model", config.model, "--mode", config.mode, "--base-url", config.base_url,
                 "--repeats", "3", "--points", options.points, "--scenarios",
                 str(options.scenarios.resolve()), "--output", str(output.resolve()),
                 "--max-seconds", str(config.max_seconds), "--max-steps", str(config.max_steps),
                 "--max-requests", str(config.max_requests)]
    if options.record:
        arguments.append("--record")
    if config.provider == "winnow" and options.server_pid is not None:
        arguments.extend(["--server-pid", str(options.server_pid)])
    return arguments


def stop_child(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGINT)
            process.wait(timeout=45)
        except (OSError, subprocess.TimeoutExpired):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)


def execute_cell(arguments: list[str], timeout: int) -> tuple[int | None, str | None]:
    try:
        # No env override: keys inherit silently. No raw child output is logged.
        process = subprocess.Popen(arguments, cwd=ROOT, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        return None, "child_unavailable"
    try:
        return process.wait(timeout=timeout), None
    except (KeyboardInterrupt, subprocess.TimeoutExpired) as error:
        stop_child(process)
        return process.returncode, (
            "matrix_cancelled" if isinstance(error, KeyboardInterrupt) else "child_timeout")


def write_record(output: Path, record: MatrixRun) -> None:
    # A crash during replacement leaves the previous complete record reviewable.
    temporary = output / ".matrix-run.tmp"
    temporary.write_text(record.model_dump_json(indent=2) + "\n")
    temporary.replace(output / "matrix-run.json")


def run_matrix(options: Options, expected: ExpectedMatrix) -> int:
    output = options.output
    frozen_path = output / "expected-matrix.json"
    frozen = expected.model_dump_json(indent=2) + "\n"
    output.mkdir(parents=True, exist_ok=False)
    frozen_path.write_text(frozen)
    record = MatrixRun(expected_sha256=hashlib.sha256(frozen.encode()).hexdigest(),
                       started_utc=datetime.now(UTC).isoformat(),
                       cells=[CellResult(cell=cell.id) for cell in expected.cells])
    write_record(output, record)
    if options.plan_only:
        print("matrix_frozen expected=105 cells=7 scenarios=5 repeats=3")
        return 0
    cancelled = False
    for cell, result in zip(expected.cells, record.cells, strict=True):
        started = time.monotonic()
        issue: str | None
        try:
            result.before = snapshot(options.app, options.simulator_runtime).fingerprint()
            result.status = "running"
            write_record(output, record)
            if (output / cell.id).exists():
                result.exit_code, issue = None, "cell_output_exists"
            else:
                result.exit_code, issue = execute_cell(
                    child_arguments(options, cell, output / cell.id),
                    15 * (cell.config.max_seconds + 120) + 120)
            if issue:
                result.issues.append(issue)
            cancelled = issue == "matrix_cancelled"
            result.status = "cancelled" if cancelled else (
                "finished" if result.exit_code == 0 and issue is None else "failed")
            result.after = snapshot(options.app, options.simulator_runtime).fingerprint()
        except KeyboardInterrupt:
            cancelled = True
            result.status = "cancelled"
            result.issues.append("matrix_cancelled")
        except (OSError, ValueError):
            result.status = "failed"
            result.issues.append("cell_metadata_unavailable")
        result.elapsed_seconds = time.monotonic() - started
        if result.before != expected.frozen.fingerprint() or result.after != result.before:
            result.issues.append("implementation_or_runtime_changed")
        write_record(output, record)
        print(f"{cell.id} {result.status}")
        if cancelled:
            break
    record.finished_utc = datetime.now(UTC).isoformat()
    write_record(output, record)
    summary = summarize(output, frozen_path)
    (output / "summary.json").write_text(summary.model_dump_json(indent=2) + "\n")
    passed = (not cancelled and not summary.invalid_files and summary.coverage is not None
              and summary.coverage.complete
              and all(row.counts.failures == 0 for row in summary.strata)
              and all(item.status == "finished" and not item.issues for item in record.cells))
    return 0 if passed else 2


class Options(argparse.Namespace):
    udid: str
    app: Path
    output: Path
    winnow_model: str
    winnow_url: str
    openrouter_url: str
    simulator_runtime: str
    points: str
    scenarios: Path
    max_seconds: int
    max_steps: int
    max_requests: int
    server_pid: int | None
    record: bool
    plan_only: bool


def parse_options() -> Options:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--udid", required=True)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--winnow-model", required=True)
    parser.add_argument("--winnow-url", default="http://127.0.0.1:8091")
    parser.add_argument("--openrouter-url", default="https://openrouter.ai/api")
    parser.add_argument("--simulator-runtime", required=True,
                        help="Operator-declared runtime label")
    parser.add_argument("--points", default="402x874")
    parser.add_argument("--scenarios", type=Path, default=ROOT / "benchmarks/scenarios.json")
    parser.add_argument("--max-seconds", type=int, default=300)
    parser.add_argument("--max-steps", type=int, default=20)
    parser.add_argument("--max-requests", type=int, default=120)
    parser.add_argument("--server-pid", type=int)
    parser.add_argument("--record", action="store_true")
    parser.add_argument("--plan-only", action="store_true")
    return parser.parse_args(namespace=Options())


def interrupt(signum: int, frame: object) -> NoReturn:
    raise KeyboardInterrupt


def main() -> int:
    options = parse_options()
    try:
        UUID(options.udid)
        if options.server_pid is not None and options.server_pid < 1:
            raise ValueError("invalid_pid")
        width, height = options.points.split("x")
        expected = ExpectedMatrix(
            screen=ScreenSize(width=float(width), height=float(height)),
            scenarios=load_manifest(options.scenarios),
            cells=cells(options.winnow_model, options.winnow_url, options.openrouter_url,
                        options.max_seconds, options.max_steps, options.max_requests),
            frozen=snapshot(options.app, options.simulator_runtime))
        previous = signal.signal(signal.SIGTERM, interrupt)
        try:
            return run_matrix(options, expected)
        finally:
            signal.signal(signal.SIGTERM, previous)
    except (OSError, ValueError):
        print("matrix_configuration_invalid_or_output_exists")
        return 2
    except KeyboardInterrupt:
        print("matrix_cancelled")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
