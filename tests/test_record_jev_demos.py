"""Persist real recorder episodes through simulated OS, HTTP and disk failures."""

from __future__ import annotations

import json
import plistlib
import subprocess
from pathlib import Path

import httpx
import pytest
from PIL import Image
from pydantic import JsonValue, TypeAdapter

from axe_control.models import ScreenSize
from benchmarks.run import BUNDLE, MANIFEST_PATH, HarnessError
from benchmarks.summarize import Episode, Oracle, load_manifest, summarize
from tools import record_jev_demos as recorder

_UDID = "11111111-2222-3333-4444-555555555555"
_SCREEN = ScreenSize(width=400.0, height=800.0)
_OBJECT: TypeAdapter[dict[str, JsonValue]] = TypeAdapter(dict[str, JsonValue])


class _VideoProcess:
    def __init__(self, path: Path, *, failed: bool, interrupt: bool) -> None:
        self.path = path
        self.failed = failed
        self.interrupt = interrupt
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode

    def send_signal(self, signal: int) -> None:
        self.returncode = 1 if self.failed else 0
        if not self.failed:
            self.path.write_bytes(b"synthetic-video-boundary")

    def wait(self, timeout: float) -> int:
        if self.interrupt:
            self.interrupt = False
            raise KeyboardInterrupt
        assert self.returncode is not None
        return self.returncode

    def kill(self) -> None:
        self.returncode = -9


class _Fixture:
    def __init__(self, root: Path, failure: str) -> None:
        self.failure = failure
        self.scenario = next(item for item in load_manifest(MANIFEST_PATH) if item.id == "duration")
        self.app = root / "FocusBench.app"
        self.app.mkdir()
        (self.app / "Info.plist").write_bytes(plistlib.dumps({
            "CFBundleIdentifier": BUNDLE, "CFBundleExecutable": "FocusBench",
        }))
        (self.app / "FocusBench").write_bytes(b"synthetic-executable-boundary")
        self.container = root / "container"
        (self.container / "Documents").mkdir(parents=True)
        self.oracle = self.container / "Documents/axe-benchmark-state.json"
        self.finished = False
        self.tree_calls = 0
        self.final_capture = False
        self.final_screenshots = 0
        self.screenshots = 0
        self.videos = 0
        self.requests: list[httpx.Request] = []

    def write_oracle(self) -> None:
        initial, expected = self.scenario.initial, self.scenario.expected
        value = Oracle(
            phase="running" if self.finished else "home",
            name=expected.name if self.finished else initial.prefill,
            duration=expected.duration if self.finished else initial.duration,
            quiet=expected.quiet if self.finished else initial.quiet,
            seed=initial.seed, screen_width=_SCREEN.width, screen_height=_SCREEN.height,
        )
        self.oracle.write_text(value.model_dump_json())

    def command(
        self, arguments: list[str], *, input: bytes | None = None,
        capture_output: bool = True, check: bool = False, timeout: float = 30,
    ) -> subprocess.CompletedProcess[bytes]:
        code, output = 0, b""
        if arguments[:4] == ["xcrun", "simctl", "list", "devices"]:
            output = json.dumps({"devices": {"synthetic": [
                {"udid": _UDID, "state": "Booted"},
            ]}}).encode()
        elif arguments[:3] == ["xcrun", "simctl", "get_app_container"]:
            output = str(self.container).encode()
        elif arguments[:3] == ["xcrun", "simctl", "launch"]:
            if self.failure == "reset":
                code = 1
            else:
                self.write_oracle()
        elif arguments[:3] in (["xcrun", "simctl", "install"],
                               ["xcrun", "simctl", "terminate"]):
            pass
        elif arguments[:2] == ["axe", "describe-ui"]:
            self.tree_calls += 1
            self.final_capture = self.tree_calls > 1
            if self.failure == "tree_command" and self.final_capture:
                code = 1
            else:
                expected = self.scenario.expected
                labels = ["FocusBench", "Session started", expected.name,
                          f"{expected.duration} minutes", "Quiet mode on"]
                if self.failure == "identity" or (
                    self.failure == "final_identity" and self.final_capture
                ):
                    labels = ["synthetic-private-app-canary"]
                output = json.dumps([{
                    "type": "StaticText", "AXLabel": label,
                    "frame": {"x": 10, "y": 30 * index + 10, "width": 200, "height": 20},
                } for index, label in enumerate(labels)]).encode()
        elif arguments[:3] == ["xcrun", "simctl", "io"] and arguments[4] == "screenshot":
            self.screenshots += 1
            if self.final_capture:
                self.final_screenshots += 1
            if self.failure == "screenshot_command" and self.final_capture:
                code = 1
            else:
                with Image.new("RGB", (400, 800), "black" if self.finished else "white") as image:
                    image.save(arguments[-1], format="PNG")
        elif arguments[:2] == ["axe", "tap"]:
            self.finished = True
            self.write_oracle()
        else:
            raise AssertionError("Unexpected native command in offline recorder test")
        return subprocess.CompletedProcess(arguments, code, output, b"")

    def video(self, arguments: list[str], *, stdout: int, stderr: int) -> _VideoProcess:
        assert arguments[:3] == ["xcrun", "simctl", "io"] and arguments[4] == "recordVideo"
        self.videos += 1
        return _VideoProcess(Path(arguments[-1]), failed=self.failure == "video_finish",
                             interrupt=self.failure == "video_interrupt")

    def respond(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.failure == "questions_write":
            (self.app.parent / "recordings/box/questions.jsonl").mkdir()
        questions = _OBJECT.validate_json(request.content)["questions"]
        assert isinstance(questions, dict)
        answers: dict[str, JsonValue] = {}
        for key, question in questions.items():
            assert isinstance(question, dict)
            if question["type"] == "choice":
                criteria = question["criteria"]
                assert isinstance(criteria, dict)
                choice = ("DONE" if self.finished else "TAP") if key == "operation" else "none"
                answers[key] = {"type": "choice", "choice": choice,
                                "probabilities": {name: float(name == choice) for name in criteria}}
            elif question["type"] == "box":
                answers[key] = {"type": "box", "confidence": 0.99,
                                "box": {"left": 0.1, "right": 0.9, "top": 0.2, "bottom": 0.4}}
            else:
                answers[key] = {"type": "noul", "noul": 0.99}
        return httpx.Response(200, json={
            "model": "typesafe/jev-1.14-20261014", "provider": "TypeSafe", "answers": answers,
            "usage": {"input_tokens": 10, "output_tokens": 0, "cost": 0.0001},
        })


def _offline(monkeypatch: pytest.MonkeyPatch, root: Path, failure: str) -> _Fixture:
    fixture = _Fixture(root, failure)
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-key")
    monkeypatch.setattr(subprocess, "run", fixture.command)
    monkeypatch.setattr(subprocess, "Popen", fixture.video)
    monkeypatch.setattr("axe_control.native.time.sleep", lambda seconds: None)
    client = httpx.Client

    def http_client(
        *, headers: dict[str, str], timeout: float, transport: httpx.BaseTransport | None,
        trust_env: bool, follow_redirects: bool,
    ) -> httpx.Client:
        return client(
            headers=headers, timeout=timeout, transport=httpx.MockTransport(fixture.respond),
            trust_env=trust_env, follow_redirects=follow_redirects,
        )

    monkeypatch.setattr(httpx, "Client", http_client)
    read_bytes, write_text, write_bytes = Path.read_bytes, Path.write_text, Path.write_bytes

    def read(path: Path) -> bytes:
        if path == fixture.oracle and fixture.final_capture and failure == "proof_interrupt":
            raise KeyboardInterrupt
        if path == fixture.oracle and fixture.final_capture and failure == "oracle_read":
            raise OSError("synthetic-read-failure")
        return read_bytes(path)

    def text(
        path: Path, data: str, encoding: str | None = None, errors: str | None = None,
        newline: str | None = None,
    ) -> int:
        if path.name == "final-tree.json" and failure == "tree_write":
            raise OSError("synthetic-write-failure")
        return write_text(path, data, encoding=encoding, errors=errors, newline=newline)

    def binary(path: Path, data: bytes) -> int:
        if path.name == "final.png" and failure == "screenshot_write":
            raise OSError("synthetic-write-failure")
        return write_bytes(path, data)

    monkeypatch.setattr(Path, "read_bytes", read)
    monkeypatch.setattr(Path, "write_text", text)
    monkeypatch.setattr(Path, "write_bytes", binary)
    return fixture


@pytest.mark.parametrize("failure", [
    "tree_command", "tree_write", "screenshot_command", "screenshot_write", "oracle_read",
    "video_finish", "final_identity",
])
def test_final_proof_failure_preserves_real_completed_episode_and_denominator(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: str,
) -> None:
    fixture = _offline(monkeypatch, tmp_path, failure)
    output = tmp_path / "recordings"
    recorder.record(_UDID, fixture.app, _SCREEN, output, ["box"], "duration", [])
    episode = Episode.model_validate_json((output / "box/episode.json").read_bytes())
    assert episode.report is not None and episode.report.status == "completed"
    assert episode.report.native_mutations == 1 and len(fixture.requests) == 5
    assert episode.proof_failures and episode.issues()
    entries: TypeAdapter[list[dict[str, JsonValue]]] = TypeAdapter(list[dict[str, JsonValue]])
    rows = entries.validate_json((output / "summary.json").read_bytes())
    assert len(rows) == 1 and rows[0]["issues"] == episode.issues()
    graded = summarize(output)
    assert not graded.invalid_files and len(graded.strata) == 1
    assert graded.strata[0].counts.episodes == graded.strata[0].counts.failures == 1
    assert graded.strata[0].counts.successes == 0
    if failure in {"tree_command", "final_identity"}:
        assert fixture.final_screenshots == 0
        assert not (output / "box/final.png").exists()
    if failure == "oracle_read":
        assert episode.evaluation.oracle is None and episode.evaluation.tree is not None
        assert episode.proof.tree and episode.proof.screenshot
    if failure == "tree_write":
        assert episode.evaluation.tree is not None and episode.evaluation.oracle is not None
        assert episode.proof.tree is None and episode.proof.screenshot


@pytest.mark.parametrize("failure", ["reset", "identity"])
def test_setup_failure_is_saved_without_unverified_fixture_capture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: str,
) -> None:
    fixture = _offline(monkeypatch, tmp_path, failure)
    output = tmp_path / "recordings"
    recorder.record(_UDID, fixture.app, _SCREEN, output, ["box"], "duration", [])
    episode = Episode.model_validate_json((output / "box/episode.json").read_bytes())
    assert episode.report is None and episode.setup_failures
    assert not fixture.requests and fixture.screenshots == fixture.videos == 0
    assert episode.proof.screenshot is None and episode.proof.video is None
    graded = summarize(output)
    assert graded.strata[0].counts.episodes == graded.strata[0].counts.failures == 1
    assert (output / "summary.json").is_file()


def test_healthy_recording_still_persists_an_independently_passing_episode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    fixture = _offline(monkeypatch, tmp_path, "healthy")
    output = tmp_path / "recordings"
    recorder.record(_UDID, fixture.app, _SCREEN, output, ["box"], "duration", [])
    episode = Episode.model_validate_json((output / "box/episode.json").read_bytes())
    assert not episode.issues() and episode.evaluation.passed
    graded = summarize(output)
    assert graded.strata[0].counts.episodes == graded.strata[0].counts.successes == 1


def test_invalid_fixture_is_refused_before_any_trial_or_capture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    fixture = _offline(monkeypatch, tmp_path, "healthy")
    (fixture.app / "Info.plist").write_bytes(plistlib.dumps({
        "CFBundleIdentifier": "synthetic.unrelated.app", "CFBundleExecutable": "FocusBench",
    }))
    output = tmp_path / "recordings"
    with pytest.raises(HarnessError):
        recorder.record(_UDID, fixture.app, _SCREEN, output, ["box"], "duration", [])
    assert not output.exists() and not fixture.requests
    assert fixture.screenshots == fixture.videos == 0


def test_capture_write_failure_does_not_claim_zero_paid_requests(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    fixture = _offline(monkeypatch, tmp_path, "questions_write")
    output = tmp_path / "recordings"
    recorder.record(_UDID, fixture.app, _SCREEN, output, ["box"], "duration", [])
    episode = Episode.model_validate_json((output / "box/episode.json").read_bytes())
    assert len(fixture.requests) == 1 and episode.report is None and episode.proof_failures
    entries: TypeAdapter[list[dict[str, JsonValue]]] = TypeAdapter(list[dict[str, JsonValue]])
    rows = entries.validate_json((output / "summary.json").read_bytes())
    assert len(rows) == 1 and rows[0]["requests"] is None and rows[0]["cost_usd"] is None
    assert summarize(output).strata[0].counts.failures == 1


@pytest.mark.parametrize("failure", ["video_interrupt", "proof_interrupt"])
def test_interrupt_during_cleanup_or_proof_retains_episode_and_stops_next_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: str,
) -> None:
    fixture = _offline(monkeypatch, tmp_path, failure)
    output = tmp_path / "recordings"
    recorder.record(_UDID, fixture.app, _SCREEN, output, ["box", "grid"], "duration", [])
    episode = Episode.model_validate_json((output / "box/episode.json").read_bytes())
    assert episode.report is not None and episode.report.status == "completed"
    assert any("cancelled" in issue for issue in episode.proof_failures)
    assert not (output / "grid").exists() and len(fixture.requests) == 5
    assert (output / "summary.json").is_file()
    assert summarize(output).strata[0].counts.failures == 1
