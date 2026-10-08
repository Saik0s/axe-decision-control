"""Command-line entrypoint. Credentials remain in environment variables or key files."""

from __future__ import annotations

import argparse
import json
import signal
import subprocess
import sys
import threading
from pathlib import Path
from types import FrameType
from typing import Literal

from pydantic import ValidationError

from .decisions import StrictModel
from .models import Event, Mode, RunConfig, ScreenSize, Task
from .native import AXeTransport, NativeError
from .providers.base import Provider
from .providers.openrouter import OpenRouterProvider
from .providers.winnow import WinnowProvider
from .runner import run


class Options(StrictModel):
    command: Literal["run", "observe", "doctor"]
    udid: str | None = None
    points: str | None = None
    provider: Literal["openrouter", "winnow"] = "openrouter"
    model: str | None = None
    base_url: str | None = None
    mode: Mode = "tree"
    goal: str | None = None
    text: list[str] = []
    max_seconds: int = 300
    max_steps: int = 20
    max_requests: int = 120
    minimum_done: float = 0.9
    minimum_inside: float = 0.5
    report: Path | None = None
    output: Path | None = None
    format: Literal["tree", "screenshot"] = "tree"
    quiet: bool = False
    api_key_file: Path | None = None
    axe: str = "axe"


def parse_points(value: str) -> ScreenSize:
    try:
        width, height = value.lower().split("x")
        return ScreenSize(width=float(width), height=float(height))
    except (ValueError, ValidationError):
        raise ValueError("Use simulator logical points in WIDTHxHEIGHT form") from None


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="axe-control",
        description="Bounded iOS Simulator control with AXe and decision models.",
    )
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "doctor", help="Check the local AXe/Xcode toolchain without simulator mutation"
    )
    native = argparse.ArgumentParser(add_help=False)
    native.add_argument("--udid", required=True, help="One explicit simulator UDID; never 'booted'")
    native.add_argument("--points", required=True, help="Logical simulator geometry, e.g. 402x874")
    native.add_argument("--axe", default="axe", help="AXe executable or path")
    observe = commands.add_parser(
        "observe", parents=[native], help="Save an explicitly requested observation"
    )
    observe.add_argument("--format", choices=["tree", "screenshot"], default="tree")
    observe.add_argument("--output", required=True, type=Path)
    control = commands.add_parser("run", parents=[native], help="Run one bounded task")
    control.add_argument("--provider", choices=["openrouter", "winnow"], default="openrouter")
    control.add_argument(
        "--model", help="Clef, Jev, or a generative model ID appropriate to the mode"
    )
    control.add_argument(
        "--base-url", help="Explicit API base URL; defaults to provider's normal route"
    )
    control.add_argument(
        "--api-key-file", type=Path, help="Key file; never pass a secret as an argument"
    )
    control.add_argument("--mode", choices=["direct", "tree", "grid"], default="tree")
    control.add_argument("--goal", required=True)
    control.add_argument(
        "--text", action="append", default=[], help="Approved literal for text entry"
    )
    control.add_argument("--max-seconds", type=int, default=300)
    control.add_argument("--max-steps", type=int, default=20)
    control.add_argument("--max-requests", type=int, default=120)
    control.add_argument("--minimum-done", type=float, default=0.9)
    control.add_argument("--minimum-inside", type=float, default=0.5)
    control.add_argument("--report", type=Path, help="Content-free JSON telemetry output")
    control.add_argument("--quiet", action="store_true", help="Print final status only")
    return result


def make_provider(options: Options) -> Provider:
    if options.provider == "winnow":
        return WinnowProvider(
            model=options.model or "Winnow-12B",
            base_url=options.base_url or "http://127.0.0.1:8091",
            api_key_file=options.api_key_file,
        )
    return OpenRouterProvider(
        model=options.model
        or ("openai/gpt-4.1-mini" if options.mode == "direct" else "cloudflare/clef"),
        base_url=options.base_url or "https://openrouter.ai/api",
        api_key_file=options.api_key_file,
    )


def doctor() -> int:
    failures = 0
    for name, arguments in (("AXe", ["axe", "--version"]), ("Xcode", ["xcodebuild", "-version"])):
        try:
            result = subprocess.run(
                arguments, capture_output=True, text=True, timeout=10, check=False
            )
            if result.returncode:
                raise OSError
            print(f"{name}: {result.stdout.strip()}")
        except (OSError, subprocess.TimeoutExpired):
            failures += 1
            print(f"{name}: unavailable")
    print("Geometry must be supplied in logical points. No simulator was changed.")
    return 2 if failures else 0


def main() -> int:
    command_parser = parser()
    options = Options.model_validate(vars(command_parser.parse_args()))
    if options.command == "doctor":
        return doctor()
    if options.udid is None or options.points is None:
        command_parser.error("Explicit simulator and logical geometry are required")
    try:
        screen = parse_points(options.points)
        transport = AXeTransport(options.udid, screen=screen, axe=options.axe)
        if options.command == "observe":
            if options.output is None:
                command_parser.error("Observation output is required")
            options.output.parent.mkdir(parents=True, exist_ok=True)
            data = (
                transport.tree().model_dump_json(indent=2).encode()
                if options.format == "tree"
                else (transport.screenshot())
            )
            options.output.write_bytes(data)
            print("Observation saved to the requested output")
            return 0
        if options.goal is None:
            command_parser.error("Goal is required")
        config = RunConfig(
            mode=options.mode,
            screen=screen,
            max_steps=options.max_steps,
            max_requests=options.max_requests,
            max_seconds=options.max_seconds,
            minimum_done=options.minimum_done,
            minimum_inside=options.minimum_inside,
        )
        provider = make_provider(options)
        cancellation = threading.Event()

        def stop(signum: int, frame: FrameType | None) -> None:
            cancellation.set()

        old_handler = signal.signal(signal.SIGINT, stop)

        def announce(event: Event) -> None:
            if not options.quiet:
                print(f"{event.step:02} {event.phase} {event.operation or ''}", flush=True)

        try:
            report = run(
                provider,
                transport,
                Task(goal=options.goal, allowed_texts=options.text),
                config,
                cancellation=cancellation,
                on_event=announce,
            )
            if options.report is not None:
                options.report.parent.mkdir(parents=True, exist_ok=True)
                options.report.write_text(report.model_dump_json(indent=2) + "\n")
            print(
                json.dumps(
                    {
                        "status": report.status,
                        "reason": report.reason,
                        "mode": report.mode,
                        "model": report.identity.resolved_model or report.identity.requested_model,
                        "requests": report.decision_requests + report.generative_requests,
                        "elapsed_seconds": round(report.elapsed_seconds, 3),
                    }
                )
            )
            return 0 if report.status == "completed" else 2
        finally:
            signal.signal(signal.SIGINT, old_handler)
            provider.close()
    except (ValueError, NativeError):
        print("Invalid configuration or unavailable native observation", file=sys.stderr)
        return 2
    except RuntimeError:
        print("Provider configuration or execution failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
