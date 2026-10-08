from __future__ import annotations

import io
import json
import subprocess
import threading
from collections.abc import Callable
from typing import Literal

import pytest
from PIL import Image, ImageDraw
from pydantic import ValidationError

from axe_control.decisions import (
    Answer,
    Capabilities,
    ChoiceAnswer,
    DecisionReply,
    DecisionRequest,
    ModelCall,
    NoulAnswer,
    ProviderIdentity,
    ProviderUsage,
)
from axe_control.grid import Cell, cells, changed
from axe_control.models import Action, AgentReply, AgentRequest, RunConfig, ScreenSize, Task
from axe_control.native import AXeTransport, NativeError
from axe_control.observation import TreeSnapshot, normalize_tree
from axe_control.runner import run

IDENTITY = ProviderIdentity(
    name="test",
    requested_model="test",
    resolved_model="test",
    endpoint="test",
    local=True,
)
USAGE = ProviderUsage(request_ms=1.0)
SCREEN = ScreenSize(width=400.0, height=800.0)


def snapshot(label: str = "Continue", *, enabled: bool = True) -> TreeSnapshot:
    return normalize_tree(
        json.dumps(
            [
                {
                    "type": "Button",
                    "AXLabel": label,
                    "AXUniqueId": "continue",
                    "enabled": enabled,
                    "frame": {"x": 20, "y": 30, "width": 100, "height": 60},
                }
            ]
        ),
        screen=SCREEN,
    )


def png(*, change: bool = False, status: bool = False) -> bytes:
    image = Image.new("RGB", (400, 800), "white")
    drawing = ImageDraw.Draw(image)
    if change:
        drawing.rectangle((50, 100, 350, 500), fill="black")
    if status:
        drawing.rectangle((0, 0, 400, 30), fill="black")
    result = io.BytesIO()
    image.save(result, format="PNG")
    return result.getvalue()


class ScriptedProvider:
    identity = IDENTITY
    capabilities = Capabilities(
        decisions=True,
        generation=True,
        vision=True,
        max_questions=64,
        max_choices=26,
    )

    def __init__(
        self,
        *,
        actions: list[Action] | None = None,
        answers: list[dict[str, Answer]] | None = None,
        after_call: Callable[[], None] | None = None,
    ) -> None:
        self.actions = actions or []
        self.answers = answers or []
        self.after_call = after_call
        self.requests: list[DecisionRequest] = []
        self._calls: list[ModelCall] = []

    @property
    def calls(self) -> tuple[ModelCall, ...]:
        return tuple(self._calls)

    def _record(self, kind: Literal["decision", "generative"]) -> None:
        assert kind in {"decision", "generative"}
        self._calls.append(ModelCall(kind=kind, succeeded=True, identity=IDENTITY, usage=USAGE))
        if self.after_call:
            self.after_call()

    def decide(self, request: DecisionRequest) -> DecisionReply:
        self.requests.append(request)
        self._record("decision")
        return DecisionReply(answers=self.answers.pop(0), identity=IDENTITY, usage=USAGE)

    def generate(self, request: AgentRequest) -> AgentReply:
        self._record("generative")
        return AgentReply(action=self.actions.pop(0), identity=IDENTITY, usage=USAGE)

    def close(self) -> None:
        pass


class ScriptedTransport:
    def __init__(
        self, snapshots: list[TreeSnapshot] | None = None, *, forbid_tree: bool = False
    ) -> None:
        self.snapshots = snapshots or [snapshot()]
        self.forbid_tree = forbid_tree
        self.commands = self.failures = self.mutations = 0
        self.actions: list[Action] = []

    def tree(self) -> TreeSnapshot:
        assert not self.forbid_tree, "Grid policy leaked accessibility data"
        self.commands += 1
        return self.snapshots.pop(0) if len(self.snapshots) > 1 else self.snapshots[0]

    def screenshot(self) -> bytes:
        self.commands += 1
        return png()

    def act(self, action: Action, snapshot: TreeSnapshot | None = None) -> None:
        self.commands += 1
        self.mutations += 1
        self.actions.append(action)


def test_snapshot_refuses_unexposed_ref_and_digest_changes_with_semantics() -> None:
    current = snapshot()
    with pytest.raises(ValueError):
        current.resolve("cached-other-screen")
    assert current.digest != snapshot("Submit").digest
    assert current.digest != snapshot(enabled=False).digest


def test_negative_control_center_is_rejected_instead_of_clamped() -> None:
    raw = '[{"type":"Button","AXLabel":"Outside","frame":{"x":-100,"y":0,"width":20,"height":20}}]'
    assert normalize_tree(raw, screen=SCREEN).elements == []


def test_action_contract_rejects_multiple_targets_and_nonfinite_points() -> None:
    with pytest.raises(ValidationError):
        Action.model_validate({"operation": "TAP", "target_ref": "e1", "point": {"x": 1, "y": 2}})
    with pytest.raises(ValidationError):
        Action.model_validate({"operation": "TAP", "point": {"x": float("nan"), "y": 2}})


def test_coarse_cell_is_subdivided_without_known_target_bounds_and_non3x_scale() -> None:
    coarse = cells((0.0, 0.0, 1000.0, 2000.0), 4, 8)[10]
    fine = cells((coarse.left, coarse.top, coarse.right, coarse.bottom), 4, 4)
    assert fine[0].left == coarse.left and fine[0].top == coarse.top
    assert fine[-1].right == coarse.right and fine[-1].bottom == coarse.bottom
    result = fine[5].point((1000, 2000), SCREEN)
    x, y = fine[5].center
    assert result.x == x * 0.4 and result.y == y * 0.4
    with pytest.raises(ValueError):
        Cell("outside", 1000, 0, 1100, 100).point((1000, 2000), SCREEN)


def test_freshness_ignores_status_only_but_detects_app_change() -> None:
    assert not changed(png(), png(status=True), tolerance=1.5)
    assert changed(png(), png(change=True), tolerance=1.5)


def test_three_stale_decisions_never_mutate_the_app() -> None:
    provider = ScriptedProvider(
        actions=[Action(operation="TAP", target_ref="e1") for _ in range(3)]
    )
    transport = ScriptedTransport([snapshot("Old"), snapshot("New")] * 3)
    report = run(
        provider, transport, Task(goal="Continue"), RunConfig(mode="direct", screen=SCREEN)
    )
    assert report.status == "blocked"
    assert report.generative_requests == 3
    assert report.native_mutations == 0 and not transport.actions


def test_cancellation_during_model_call_prevents_the_pending_native_action() -> None:
    cancellation = threading.Event()
    provider = ScriptedProvider(
        actions=[Action(operation="TAP", target_ref="e1")],
        after_call=cancellation.set,
    )
    transport = ScriptedTransport()
    report = run(
        provider,
        transport,
        Task(goal="Continue"),
        RunConfig(mode="direct"),
        cancellation=cancellation,
    )
    assert report.status == "cancelled"
    assert transport.mutations == 0 and transport.commands == 1


def test_request_budget_is_shared_with_completion_and_prevents_further_model_calls() -> None:
    provider = ScriptedProvider(actions=[Action(operation="DONE")])
    report = run(
        provider,
        ScriptedTransport(),
        Task(goal="Continue"),
        RunConfig(mode="direct", max_requests=1),
    )
    assert report.status == "budget_exhausted" and report.generative_requests == 1
    assert report.native_mutations == 0


def test_grid_completion_never_reads_tree_or_oracle() -> None:
    provider = ScriptedProvider(
        answers=[
            {"operation": ChoiceAnswer(choice="DONE", probabilities={"DONE": 1.0, "TAP": 0.0})},
            {"complete": NoulAnswer(noul=0.98)},
            {"complete": NoulAnswer(noul=0.99)},
        ]
    )
    report = run(
        provider,
        ScriptedTransport(forbid_tree=True),
        Task(goal="Observe the result"),
        RunConfig(mode="grid", screen=SCREEN),
    )
    assert report.status == "completed" and report.decision_requests == 3
    assert report.native_mutations == 0
    assert all(request.images for request in provider.requests)


def test_tree_can_verify_completion_when_result_screen_exposes_no_controls() -> None:
    final = normalize_tree(
        '[{"type":"StaticText","AXLabel":"Finished",'
        '"frame":{"x":20,"y":100,"width":200,"height":100}}]',
        screen=SCREEN,
    )
    assert not final.elements
    provider = ScriptedProvider(
        answers=[
            {
                "operation": ChoiceAnswer(choice="DONE", probabilities={"DONE": 1.0, "TAP": 0.0}),
                "target": ChoiceAnswer(
                    choice="none", probabilities={"none": 1.0, "unavailable": 0.0}
                ),
            },
            {"complete": NoulAnswer(noul=0.99)},
            {"complete": NoulAnswer(noul=0.99)},
        ]
    )
    report = run(
        provider,
        ScriptedTransport([final]),
        Task(goal="Finish"),
        RunConfig(mode="tree", screen=SCREEN),
    )
    assert report.status == "completed" and report.decision_requests == 3
    assert report.native_mutations == 0


def test_typing_keeps_metacharacters_in_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[tuple[list[str], bytes | None]] = []

    def command(arguments: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        data = kwargs["input"]
        assert data is None or isinstance(data, bytes)
        commands.append((arguments, data))
        return subprocess.CompletedProcess(arguments, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", command)
    transport = AXeTransport("explicit-test-udid", screen=SCREEN, settle_seconds=0)
    supplied = "synthetic $(never-run) `never-run`"
    transport.act(Action(operation="TYPE_TEXT", target_ref="e1", text=supplied), snapshot())
    assert commands[-1][1] == supplied.encode()
    assert all(supplied not in arguments for arguments, _ in commands)
    assert commands[1][0][1:6] == ["key-combo", "--modifiers", "227", "--key", "4"]


def test_disabled_target_never_invokes_native_tap(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Disabled target reached native execution")

    monkeypatch.setattr(subprocess, "run", forbidden)
    transport = AXeTransport("explicit-test-udid", screen=SCREEN)
    with pytest.raises(NativeError):
        transport.act(Action(operation="TAP", target_ref="e1"), snapshot(enabled=False))
    assert transport.commands == 0
