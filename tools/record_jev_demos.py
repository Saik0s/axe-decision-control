"""Record matched Jev 1.14 demos and independently grade the synthetic app outcome.

This command makes paid OpenRouter calls and changes only the selected simulator.
It explicitly captures the synthetic app's screenshots and typed question/answer
pairs. Credentials and embedded image bytes are never persisted.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw
from pydantic import JsonValue

from axe_control.decisions import DecisionReply, DecisionRequest, Question, StrictModel
from axe_control.models import Event, Mode, RunConfig, RunReport, ScreenSize, Task
from axe_control.native import AXeTransport, NativeError
from axe_control.providers.openrouter import OpenRouterProvider
from axe_control.runner import run
from benchmarks.run import (
    MANIFEST_PATH,
    HarnessError,
    Video,
    fixture_tree,
    read_oracle,
    reset,
    simctl,
    verify_fixture,
)
from benchmarks.summarize import (
    Episode,
    Oracle,
    Proof,
    ProviderConfig,
    Scenario,
    SyntheticTree,
    evaluate,
    load_manifest,
)

MODEL = "typesafe/jev-1.14"


class JudgmentCapture(StrictModel):
    call: int
    image_count: int
    state: JsonValue
    questions: dict[str, Question]
    reply: DecisionReply


class CapturedProvider(OpenRouterProvider):
    def __init__(self, directory: Path) -> None:
        super().__init__(MODEL)
        self.directory = directory

    def decide(self, request: DecisionRequest) -> DecisionReply:
        reply = super().decide(request)
        # Deliberate synthetic-demo capture; normal provider telemetry remains content-free.
        with (self.directory / "questions.jsonl").open("a") as stream:
            stream.write(JudgmentCapture(
                call=len(self.calls), image_count=len(request.images),
                state=request.state, questions=request.questions, reply=reply,
            ).model_dump_json() + "\n")
        return reply


class CapturedTransport(AXeTransport):
    def __init__(self, udid: str, screen: ScreenSize, directory: Path) -> None:
        super().__init__(udid, screen=screen)
        self.directory = directory
        self.step = 0

    def screenshot(self) -> bytes:
        data = super().screenshot()
        path = self.directory / f"step-{self.step:02}.png"
        if self.step and not path.exists():
            path.write_bytes(data)
        return data

    def event(self, event: Event) -> None:
        if event.phase == "observe":
            self.step = event.step
        if event.phase == "decide" and event.box is not None:
            source = self.directory / f"step-{event.step:02}.png"
            with Image.open(source) as original:
                image = original.convert("RGB")
            box = event.box
            draw = ImageDraw.Draw(image)
            draw.rectangle((box.left * image.width, box.top * image.height,
                            box.right * image.width, box.bottom * image.height),
                           outline="#087c64", width=max(3, image.width // 150))
            if event.tap_point is not None:
                x = event.tap_point.x / self.screen.width * image.width
                y = event.tap_point.y / self.screen.height * image.height
                radius = max(6, image.width // 75)
                draw.ellipse((x-radius, y-radius, x+radius, y+radius),
                             fill="#bd4426", outline="white", width=3)
            image.save(self.directory / f"step-{event.step:02}-box.png")
        print(f"{event.step:02} {event.phase} {event.operation or ''}", flush=True)


def capture_final(
    native: AXeTransport, scenarios: list[Scenario], oracle_file: Path, directory: Path,
    proof: Proof, failures: list[str],
) -> tuple[Oracle | None, SyntheticTree | None]:
    tree = None
    oracle = None
    try:
        tree = fixture_tree(native, scenarios)
    except (HarnessError, NativeError, OSError):
        failures.append("final_tree_unavailable")
    if tree is not None:
        try:
            (directory / "final-tree.json").write_text(tree.model_dump_json(indent=2) + "\n")
            proof.tree = "final-tree.json"
        except OSError:
            failures.append("final_tree_write_failed")
        try:
            (directory / "final.png").write_bytes(native.screenshot())
            proof.screenshot = "final.png"
        except (NativeError, OSError):
            failures.append("final_screenshot_unavailable")
    else:
        # A failed identity check must never lead to a capture of an unrelated app.
        failures.append("final_screenshot_skipped_unverified_fixture")
    try:
        oracle = read_oracle(oracle_file)
    except (HarnessError, OSError):
        failures.append("final_oracle_unavailable")
    return oracle, tree


def record(udid: str, app: Path, screen: ScreenSize, output: Path, modes: list[Mode],
           scenario_id: str, targets: list[str]) -> None:
    scenarios = load_manifest(MANIFEST_PATH)
    scenario = next(item for item in scenarios if item.id == scenario_id)
    verify_fixture(udid, app)
    output.mkdir(parents=True, exist_ok=False)
    simctl(udid, "install", str(app.resolve()))
    summaries: list[dict[str, JsonValue]] = []
    for mode in modes:
        directory = output / mode
        directory.mkdir()
        native = CapturedTransport(udid, screen, directory)
        config = RunConfig(mode=mode, screen=screen, max_seconds=240, max_requests=120)
        report: RunReport | None = None
        oracle_file: Path | None = None
        video: Video | None = None
        proof = Proof()
        setup_failures: list[str] = []
        proof_failures: list[str] = []
        fixture_ready = False
        interrupted = False
        try:
            oracle_file = reset(udid, scenario, scenario.initial.seed, screen)
            fixture_tree(native, scenarios)  # Never passed to the visual policy.
            fixture_ready = True
            video = Video(udid, directory / "original.mp4")
            with CapturedProvider(directory) as provider:
                video.start()
                report = run(provider, native, Task(goal=scenario.goal,
                             allowed_texts=scenario.allowed_texts,
                             target_descriptions=targets if mode == "box" else []),
                             config, on_event=native.event)
        except HarnessError as error:
            failures = proof_failures if fixture_ready else setup_failures
            failures.extend(str(error).split(","))
        except (OSError, RuntimeError, ValueError):
            failures = proof_failures if fixture_ready else setup_failures
            failures.append("recording_failed" if fixture_ready else "fixture_setup_failed")
        except KeyboardInterrupt:
            interrupted = True
            failures = proof_failures if fixture_ready else setup_failures
            failures.append("recording_cancelled")
        finally:
            if video is not None and video.process is not None:
                try:
                    video_ok = video.stop()
                except KeyboardInterrupt:
                    interrupted = True
                    proof_failures.append("recording_cancelled")
                    try:
                        video_ok = video.stop()
                    except (OSError, subprocess.SubprocessError, KeyboardInterrupt):
                        video_ok = False
                except (OSError, subprocess.SubprocessError):
                    video_ok = False
                if video_ok:
                    proof.video = "original.mp4"
                else:
                    proof_failures.append("video_finish_failed")
        if report is not None:
            try:
                (directory / "run-report.json").write_text(report.model_dump_json(indent=2) + "\n")
            except OSError:
                proof_failures.append("run_report_write_failed")
        oracle = None
        final_tree = None
        if fixture_ready and oracle_file is not None:
            try:
                oracle, final_tree = capture_final(
                    native, scenarios, oracle_file, directory, proof, proof_failures,
                )
            except KeyboardInterrupt:
                interrupted = True
                proof_failures.append("final_capture_cancelled")
        episode = Episode(
            scenario=scenario, repetition=0, seed=scenario.initial.seed, screen=screen,
            provider_config=ProviderConfig(provider="openrouter", model=MODEL, mode=mode,
                base_url="https://openrouter.ai/api", max_seconds=config.max_seconds,
                max_steps=config.max_steps, max_requests=config.max_requests),
            report=report,
            exit_code=None if report is None else (0 if report.status == "completed" else 2),
            evaluation=evaluate(scenario, scenario.initial.seed, screen, oracle, final_tree),
            proof=proof, setup_failures=setup_failures, proof_failures=proof_failures,
        )
        (directory / "episode.json").write_text(episode.model_dump_json(indent=2) + "\n")
        summary: dict[str, JsonValue] = {
            "mode": mode, "status": report.status if report is not None else "failed",
            "issues": [issue for issue in episode.issues()],
            "outcome_reached": episode.evaluation.passed,
            "model": report.identity.resolved_model if report is not None else None,
            "requests": report.decision_requests if report is not None else None,
            "seconds": report.elapsed_seconds if report is not None else None,
            "cost_usd": report.reported_cost_usd if report is not None else None,
        }
        summaries.append(summary)
        print(json.dumps(summary), flush=True)
        (output / "summary.json").write_text(json.dumps(summaries, indent=2) + "\n")
        if interrupted:
            break


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--udid", required=True)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--points", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scenario", choices=["basic", "duration", "quiet-off", "prefilled",
                                             "scroll"], default="basic")
    parser.add_argument("--target", action="append", default=[],
                        help="Caller-described candidate control, used only by box mode")
    parser.add_argument("--modes", nargs="+", choices=["tree", "grid", "box"],
                        default=["tree", "grid", "box"])
    args = parser.parse_args()
    from axe_control.cli import parse_points
    modes: list[Mode] = []
    for value in args.modes:
        if value == "tree":
            modes.append("tree")
        elif value == "grid":
            modes.append("grid")
        elif value == "box":
            modes.append("box")
    record(args.udid, args.app, parse_points(args.points), args.output, modes, args.scenario,
           args.target)


if __name__ == "__main__":
    main()
