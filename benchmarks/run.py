#!/usr/bin/env python3
"""Run matched synthetic episodes on one existing, explicitly selected simulator."""

from __future__ import annotations

import argparse
import os
import plistlib
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter, ValidationError

from axe_control.models import RunReport, ScreenSize
from axe_control.native import AXeTransport, NativeError

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmarks.resources import ProcessSampler, ResourceReport
from benchmarks.summarize import (
    Episode,
    Oracle,
    Proof,
    ProviderConfig,
    Scenario,
    SyntheticTree,
    evaluate,
    initial_issues,
    load_manifest,
    safe_endpoint,
    sanitize_tree,
)

BUNDLE = "dev.axecontrol.focusbench"
MANIFEST_PATH = Path(__file__).with_name("scenarios.json")


class HarnessError(RuntimeError):
    """An error code only, never captured output or input values."""


def command(arguments: list[str], timeout: float = 30) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(arguments, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise HarnessError("native_command_unavailable") from None


def simctl(udid: str, operation: str, *arguments: str) -> bytes:
    result = command(["xcrun", "simctl", operation, udid, *arguments])
    if result.returncode:
        raise HarnessError(f"simctl_{operation}_failed")
    return result.stdout


class Device(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")
    udid: str
    state: str


class DeviceList(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")
    devices: dict[str, list[Device]]


def verify_fixture(udid: str, app: Path) -> None:
    try:
        UUID(udid)
        result = command(["xcrun", "simctl", "list", "devices", "--json"])
        if result.returncode:
            raise HarnessError("device_list_failed")
        devices = DeviceList.model_validate_json(result.stdout)
        selected = [
            device
            for group in devices.devices.values()
            for device in group
            if device.udid.lower() == udid.lower()
        ]
        if len(selected) != 1 or selected[0].state != "Booted":
            raise HarnessError("selected_device_not_booted")
        with (app / "Info.plist").open("rb") as stream:
            info = TypeAdapter(dict[str, JsonValue]).validate_python(plistlib.load(stream))
        if (
            info.get("CFBundleIdentifier") != BUNDLE
            or info.get("CFBundleExecutable") != "FocusBench"
            or not (app / "FocusBench").is_file()
        ):
            raise HarnessError("supplied_app_not_focusbench")
    except (ValueError, OSError, plistlib.InvalidFileException):
        raise HarnessError("device_or_fixture_invalid") from None


def terminate(udid: str) -> None:
    result = command(["xcrun", "simctl", "terminate", udid, BUNDLE])
    if result.returncode:
        diagnostic = result.stderr.decode(errors="replace").lower()
        benign = ("not running", "found nothing to terminate", "no such process")
        if not any(message in diagnostic for message in benign):
            raise HarnessError("fixture_terminate_failed")


def oracle_path(udid: str) -> Path:
    raw = simctl(udid, "get_app_container", BUNDLE, "data")
    container = Path(raw.decode().strip())
    if not container.is_absolute() or not container.is_dir():
        raise HarnessError("fixture_container_invalid")
    return container / "Documents" / "axe-benchmark-state.json"


def read_oracle(path: Path) -> Oracle:
    try:
        return Oracle.model_validate_json(path.read_bytes())
    except (OSError, ValidationError):
        raise HarnessError("fixture_oracle_unavailable") from None


def reset(udid: str, scenario: Scenario, seed: int, screen: ScreenSize) -> Path:
    terminate(udid)
    path = oracle_path(udid)
    previous_mtime = path.stat().st_mtime_ns if path.exists() else None
    initial = scenario.initial
    simctl(
        udid,
        "launch",
        BUNDLE,
        "--seed",
        str(seed),
        "--duration",
        str(initial.duration),
        "--quiet",
        str(initial.quiet).lower(),
        "--prefill",
        initial.prefill,
        "--scroll",
        str(initial.scroll).lower(),
    )
    deadline = time.monotonic() + 10
    issues = ["initial_oracle_not_refreshed"]
    while time.monotonic() < deadline:
        try:
            oracle = read_oracle(path)
            issues = initial_issues(oracle, scenario, seed, screen)
            if path.stat().st_mtime_ns == previous_mtime:
                issues.append("initial_oracle_not_refreshed")
            if not issues:
                return path
        except (HarnessError, OSError):
            issues = ["initial_oracle_unavailable"]
        time.sleep(0.1)
    raise HarnessError(",".join(issues))


def fixture_tree(native: AXeTransport, scenarios: list[Scenario]) -> SyntheticTree:
    tree = native.tree()
    if "FocusBench" not in tree.text:
        raise HarnessError("fixture_not_visible")
    return sanitize_tree(tree.text, scenarios)


class Video:
    def __init__(self, udid: str, path: Path) -> None:
        self.udid = udid
        self.path = path
        self.process: subprocess.Popen[bytes] | None = None

    def start(self) -> None:
        try:
            self.process = subprocess.Popen(
                ["xcrun", "simctl", "io", self.udid, "recordVideo", "--codec=h264", str(self.path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(0.5)
            if self.process.poll() is not None:
                raise HarnessError("video_start_failed")
        except OSError:
            raise HarnessError("video_start_failed") from None

    def stop(self) -> bool:
        if self.process is None:
            return False
        try:
            if self.process.poll() is None:
                self.process.send_signal(signal.SIGINT)
            self.process.wait(timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            self.process.kill()
            self.process.wait(timeout=5)
            return False
        return self.process.returncode == 0 and self.path.is_file() and self.path.stat().st_size > 0


def cli_arguments(
    udid: str, screen: ScreenSize, scenario: Scenario, config: ProviderConfig, report: Path
) -> list[str]:
    arguments = [
        "axe-control",
        "run",
        "--provider",
        config.provider,
        "--model",
        config.model,
        "--base-url",
        config.base_url,
        "--mode",
        config.mode,
        "--udid",
        udid,
        "--points",
        f"{screen.width:g}x{screen.height:g}",
        "--goal",
        scenario.goal,
        "--max-seconds",
        str(config.max_seconds),
        "--max-steps",
        str(config.max_steps),
        "--max-requests",
        str(config.max_requests),
        "--report",
        str(report),
    ]
    for value in scenario.allowed_texts:
        arguments.extend(["--text", value])
    return arguments


def safe_report(path: Path) -> RunReport:
    try:
        report = RunReport.model_validate_json(path.read_bytes())
        for identity in [report.identity, *(call.identity for call in report.calls)]:
            safe_endpoint(identity.endpoint)
        return report
    except (OSError, ValidationError, ValueError):
        # Invalid provider output must not become a durable HTTP-body error dump.
        if path.is_file():
            path.write_text('{"error":"invalid_run_report"}\n')
        raise HarnessError("invalid_run_report") from None


def run_cli(arguments: list[str], max_seconds: int) -> tuple[int | None, str | None]:
    try:
        process = subprocess.Popen(
            arguments, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True
        )
    except OSError:
        return None, "cli_unavailable"
    try:
        return process.wait(timeout=max_seconds + 45), None
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
        issue = (
            "cli_timeout" if isinstance(error, subprocess.TimeoutExpired) else "harness_cancelled"
        )
        try:
            os.killpg(process.pid, signal.SIGINT)
            process.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
        return process.returncode, issue


def run_episode(
    udid: str,
    screen: ScreenSize,
    scenario: Scenario,
    repetition: int,
    scenarios: list[Scenario],
    config: ProviderConfig,
    directory: Path,
    server_pid: int | None,
    record: bool,
    prerequisite: list[str],
) -> Episode:
    directory.mkdir(parents=True, exist_ok=False)
    seed = scenario.initial.seed + 1009 * repetition
    failures = list(prerequisite)
    proof_failures: list[str] = []
    report: RunReport | None = None
    exit_code: int | None = None
    oracle: Oracle | None = None
    tree: SyntheticTree | None = None
    resources = (
        ResourceReport(pid=server_pid, errors=["agent_not_started"])
        if server_pid is not None
        else None
    )
    proof = Proof()
    native = AXeTransport(udid, screen=screen)
    sampler = ProcessSampler(server_pid) if server_pid is not None else None
    sampler_started = False
    video = Video(udid, directory / "original.mp4") if record else None
    state: Path | None = None
    report_path = directory / "run-report.json"
    try:
        if not failures:
            state = reset(udid, scenario, seed, screen)
            fixture_tree(native, scenarios)
            if video:
                video.start()
            if sampler:
                try:
                    sampler.start()
                    sampler_started = True
                except RuntimeError:
                    if server_pid is not None:
                        resources = ResourceReport(
                            pid=server_pid, errors=["server_pid_unavailable"]
                        )
                    raise HarnessError("server_pid_unavailable") from None
            exit_code, cli_issue = run_cli(
                cli_arguments(udid, screen, scenario, config, report_path), config.max_seconds
            )
            if cli_issue:
                proof_failures.append(cli_issue)
            if report_path.exists():
                report = safe_report(report_path)
            else:
                proof_failures.append("run_report_missing")
    except (HarnessError, NativeError, ValueError, RuntimeError) as error:
        code = str(error) if isinstance(error, HarnessError) else "setup_or_capture_failed"
        (proof_failures if state is not None and report_path.exists() else failures).extend(
            code.split(",")
        )
    except OSError:
        failures.append("fixture_setup_io_failed")
    except KeyboardInterrupt:
        proof_failures.append("harness_cancelled")
    finally:
        if sampler and sampler_started:
            resources = sampler.stop()
        if video and video.process is not None:
            if video.stop():
                proof.video = "original.mp4"
            else:
                proof_failures.append("video_finish_failed")
    if state is not None:
        try:
            oracle = read_oracle(state)
        except HarnessError:
            proof_failures.append("final_oracle_unavailable")
        try:
            tree = fixture_tree(native, scenarios)
            (directory / "final-tree.json").write_text(tree.model_dump_json(indent=2) + "\n")
            proof.tree = "final-tree.json"
            (directory / "final.png").write_bytes(native.screenshot())
            proof.screenshot = "final.png"
        except (HarnessError, NativeError, OSError):
            proof_failures.append("final_fixture_proof_unavailable")
    episode = Episode(
        scenario=scenario,
        repetition=repetition,
        seed=seed,
        screen=screen,
        provider_config=config,
        report=report,
        exit_code=exit_code,
        evaluation=evaluate(scenario, seed, screen, oracle, tree),
        setup_failures=failures,
        proof_failures=proof_failures,
        resources=resources,
        proof=proof,
    )
    (directory / "episode.json").write_text(episode.model_dump_json(indent=2) + "\n")
    return episode


class Options(argparse.Namespace):
    udid: str
    app: Path
    provider: Literal["openrouter", "winnow"]
    model: str
    mode: Literal["direct", "tree", "grid", "box"]
    base_url: str
    repeats: int
    points: str
    scenarios: Path
    output: Path
    server_pid: int | None
    record: bool
    max_seconds: int
    max_steps: int
    max_requests: int


def parse_options() -> Options:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--udid", required=True)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--provider", choices=("openrouter", "winnow"), required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--mode", choices=("direct", "tree", "grid", "box"), required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--points", default="402x874")
    parser.add_argument("--scenarios", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--server-pid", type=int)
    parser.add_argument("--record", action="store_true")
    parser.add_argument("--max-seconds", type=int, default=300)
    parser.add_argument("--max-steps", type=int, default=20)
    parser.add_argument("--max-requests", type=int, default=120)
    options = Options()
    parser.parse_args(namespace=options)
    return options


def main() -> int:
    options = parse_options()
    try:
        if options.repeats < 1 or (options.server_pid is not None and options.server_pid < 1):
            raise ValueError("Invalid repeat count or PID")
        UUID(options.udid)
        width, height = options.points.split("x")
        screen = ScreenSize(width=float(width), height=float(height))
        config = ProviderConfig(
            provider=options.provider,
            model=options.model,
            mode=options.mode,
            base_url=options.base_url,
            max_seconds=options.max_seconds,
            max_steps=options.max_steps,
            max_requests=options.max_requests,
        )
        scenarios = load_manifest(options.scenarios)
        # Refuse collisions before any simulator mutation; each matrix cell owns a fresh root.
        options.output.mkdir(parents=True, exist_ok=False)
    except (ValueError, OSError):
        print("benchmark_configuration_invalid_or_output_exists")
        return 2
    prerequisite: list[str] = []
    try:
        verify_fixture(options.udid, options.app)
        simctl(options.udid, "install", str(options.app.resolve()))
    except HarnessError as error:
        prerequisite.append(str(error))
    failed = False
    for index, scenario in enumerate(scenarios):
        for repetition in range(options.repeats):
            episode = run_episode(
                options.udid,
                screen,
                scenario,
                repetition,
                scenarios,
                config,
                options.output / scenario.id / f"repeat-{repetition}",
                options.server_pid,
                options.record and index == repetition == 0,
                prerequisite,
            )
            passed = not episode.issues()
            failed |= not passed
            print(f"{scenario.id} repeat={repetition} {'passed' if passed else 'failed'}")
            if "harness_cancelled" in episode.proof_failures:
                return 2
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
