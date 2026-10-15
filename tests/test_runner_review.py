from __future__ import annotations

import io
import threading
from typing import Literal

import pytest
from PIL import Image, ImageDraw
from pydantic import JsonValue
from test_control import SCREEN, ScriptedProvider, ScriptedTransport, png, snapshot

from axe_control.context import RunContext
from axe_control.decisions import Capabilities, ChoiceAnswer, NoulAnswer
from axe_control.grid import Cell, changed
from axe_control.models import Action, ActionHistory, Event, Mode, RunConfig, Task
from axe_control.observation import TreeSnapshot, normalize_tree
from axe_control.policies import grid
from axe_control.runner import run


def test_cancellation_in_action_callback_prevents_mutation() -> None:
    cancellation = threading.Event()
    provider = ScriptedProvider(actions=[Action(operation="TAP", target_ref="e1")])
    transport = ScriptedTransport()

    def cancel(event: Event) -> None:
        if event.phase == "act":
            cancellation.set()

    report = run(
        provider,
        transport,
        Task(goal="Continue"),
        RunConfig(mode="direct"),
        cancellation=cancellation,
        on_event=cancel,
    )
    assert report.status == "cancelled"
    assert transport.mutations == 0 and not transport.actions


def test_expired_budget_in_action_callback_prevents_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [0.0]
    monkeypatch.setattr("axe_control.context.time.monotonic", lambda: clock[0])
    provider = ScriptedProvider(actions=[Action(operation="TAP", target_ref="e1")])
    transport = ScriptedTransport()

    def expire(event: Event) -> None:
        if event.phase == "act":
            clock[0] = 2.0

    report = run(
        provider,
        transport,
        Task(goal="Continue"),
        RunConfig(mode="direct", max_seconds=1),
        on_event=expire,
    )
    assert report.status == "budget_exhausted"
    assert transport.mutations == 0


@pytest.mark.parametrize("mode", ["direct", "grid"])
def test_unsupported_mode_rejects_before_native_observation(mode: str) -> None:
    provider = ScriptedProvider()
    provider.capabilities = Capabilities(
        decisions=True, generation=False, vision=False, max_questions=64, max_choices=26
    )
    transport = ScriptedTransport(forbid_tree=True)
    config = RunConfig.model_validate({"mode": mode, "screen": SCREEN})
    report = run(provider, transport, Task(goal="Continue"), config)
    assert report.status == "blocked"
    assert transport.commands == 0 and not provider.calls


def test_direct_completion_rejects_state_changed_during_final_call() -> None:
    transport = ScriptedTransport([snapshot("Finished")])
    provider = ScriptedProvider(actions=[Action(operation="DONE"), Action(operation="DONE")])

    def change_after_confirmation() -> None:
        if len(provider.calls) == 2:
            transport.snapshots[:] = [snapshot("Unfinished")]

    provider.after_call = change_after_confirmation
    report = run(provider, transport, Task(goal="Finish"), RunConfig(mode="direct", max_steps=1))
    assert report.status == "budget_exhausted"
    assert report.events[-1].state_changed is True
    assert report.events[-1].completion_belief is None


@pytest.mark.parametrize("confirmed", [False, True])
def test_direct_completion_requires_fresh_done_even_with_zero_threshold(confirmed: bool) -> None:
    confirmation = (Action(operation="DONE") if confirmed
                    else Action(operation="TAP", target_ref="e1"))
    provider = ScriptedProvider(actions=[Action(operation="DONE"), confirmation])
    transport = ScriptedTransport()
    report = run(provider, transport, Task(goal="Finish"),
                 RunConfig(mode="direct", minimum_done=0.0, max_steps=1))
    assert report.status == ("completed" if confirmed else "blocked")
    assert report.native_mutations == 0 and not transport.actions
    assert report.generative_requests == 2
    assert report.events[-1].completion_belief is None


@pytest.mark.parametrize("target,role,allowed", [
    (None, "Button", False), ("e1", "Button", False),
    ("e1", "TextField", True), ("e1", "SecureTextField", True),
])
def test_direct_text_entry_requires_a_current_editable_target(
    target: str | None, role: str, allowed: bool,
) -> None:
    current = normalize_tree(
        '[{"type":"' + role + '","AXLabel":"Name","AXUniqueId":"name",'
        '"frame":{"x":20,"y":30,"width":100,"height":60}}]', screen=SCREEN)
    action = Action(operation="TYPE_TEXT", target_ref=target, text="Synthetic name")
    transport = ScriptedTransport([current])
    report = run(ScriptedProvider(actions=[action]), transport,
                 Task(goal="Enter the approved name", allowed_texts=["Synthetic name"]),
                 RunConfig(mode="direct", max_steps=1))
    assert report.status == ("budget_exhausted" if allowed else "blocked")
    assert transport.actions == ([action] if allowed else [])
    assert report.native_mutations == int(allowed)
    assert "Synthetic name" not in report.model_dump_json()


@pytest.mark.parametrize("mode", ["direct", "grid"])
@pytest.mark.parametrize("stop", ["cancelled", "deadline"])
@pytest.mark.parametrize("boundary", ["stale", "post_action", "verify_callback", "confirmation"])
def test_cooperative_stop_wins_at_terminal_observation_boundaries(
    monkeypatch: pytest.MonkeyPatch, mode: Mode,
    stop: Literal["cancelled", "deadline"],
    boundary: Literal["stale", "post_action", "verify_callback", "confirmation"],
) -> None:
    clock = [0.0]
    monkeypatch.setattr("axe_control.context.time.monotonic", lambda: clock[0])
    cancellation = threading.Event()
    observations = 0
    stop_observation = 6 if boundary == "stale" else 3

    def request_stop() -> None:
        if stop == "cancelled":
            cancellation.set()
        else:
            clock[0] = 1.0

    def observed() -> None:
        nonlocal observations
        observations += 1
        if boundary != "verify_callback" and observations == stop_observation:
            request_stop()

    class BoundaryTransport(ScriptedTransport):
        def tree(self) -> TreeSnapshot:
            result = super().tree()
            observed()
            return result

        def screenshot(self) -> bytes:
            self.commands += 1
            result = png(change=boundary == "stale" and observations % 2 == 1)
            observed()
            return result

    def on_event(event: Event) -> None:
        if boundary == "verify_callback" and event.phase == "verify":
            request_stop()

    transport = BoundaryTransport(
        [snapshot("Old"), snapshot("New")] * 3 if boundary == "stale" else None,
        forbid_tree=mode == "grid")
    if mode == "direct":
        provider = ScriptedProvider(actions=(
            [Action(operation="DONE"), Action(operation="DONE")]
            if boundary == "confirmation" else
            [Action(operation="SCROLL_DOWN") for _ in range(3)]))
    elif boundary == "confirmation":
        provider = ScriptedProvider(answers=[
            {"operation": ChoiceAnswer(choice="DONE", probabilities={"DONE": 1.0, "TAP": 0.0})},
            {"complete": NoulAnswer(noul=0.99)}, {"complete": NoulAnswer(noul=0.99)},
        ])
    else:
        provider = ScriptedProvider(answers=[{
            "operation": ChoiceAnswer(choice="SCROLL_DOWN",
                                      probabilities={"SCROLL_DOWN": 1.0, "DONE": 0.0}),
        } for _ in range(3)])
    report = run(provider, transport, Task(goal="Continue"),
                 RunConfig(mode=mode, screen=SCREEN, max_seconds=1,
                           max_steps=3 if boundary == "stale" else 1),
                 cancellation=cancellation, on_event=on_event)
    assert report.status == ("cancelled" if stop == "cancelled" else "budget_exhausted")
    assert report.reason == ("Run cancelled before its next operation" if stop == "cancelled"
                             else "Wall-clock budget exhausted")
    expected_actions = 1 if boundary in {"post_action", "verify_callback"} else 0
    assert len(transport.actions) == report.native_mutations == expected_actions
    assert observations == stop_observation


def test_final_decision_belief_is_saved_even_when_it_disagrees_with_plan() -> None:
    provider = ScriptedProvider(
        answers=[
            {"operation": ChoiceAnswer(choice="DONE", probabilities={"DONE": 1.0, "TAP": 0.0})},
            {"complete": NoulAnswer(noul=0.99)},
            {"complete": NoulAnswer(noul=0.10)},
        ]
    )
    report = run(
        provider,
        ScriptedTransport(forbid_tree=True),
        Task(goal="Finish"),
        RunConfig(mode="grid", screen=SCREEN),
    )
    assert report.status == "blocked"
    assert report.events[-1].completion_belief == 0.10


def test_grid_completion_rejects_image_changed_during_final_call() -> None:
    class ChangingTransport(ScriptedTransport):
        image_changed = False

        def screenshot(self) -> bytes:
            self.commands += 1
            return png(change=self.image_changed)

    transport = ChangingTransport(forbid_tree=True)
    provider = ScriptedProvider(
        answers=[
            {"operation": ChoiceAnswer(choice="DONE", probabilities={"DONE": 1.0, "TAP": 0.0})},
            {"complete": NoulAnswer(noul=0.99)},
            {"complete": NoulAnswer(noul=0.99)},
        ]
    )

    def change_after_confirmation() -> None:
        if len(provider.calls) == 3:
            transport.image_changed = True

    provider.after_call = change_after_confirmation
    report = run(
        provider, transport, Task(goal="Finish"), RunConfig(mode="grid", screen=SCREEN, max_steps=1)
    )
    assert report.status == "budget_exhausted"
    assert report.events[-1].state_changed is True
    assert report.events[-1].completion_belief == 0.99


@pytest.mark.parametrize(
    "history,needs_focus",
    [
        ([], True),
        ([ActionHistory(operation="TAP", text_focus_key="t1")], False),
        ([ActionHistory(operation="TAP", text_focus_key="t2")], True),
        ([ActionHistory(operation="TYPE_TEXT", text_focus_key="t1")], True),
        ([ActionHistory(operation="TAP")], True),
    ],
)
def test_grid_text_requires_recent_focus_for_the_selected_literal(
    monkeypatch: pytest.MonkeyPatch, history: list[ActionHistory], needs_focus: bool
) -> None:
    provider = ScriptedProvider(
        answers=[
            {
                "operation": ChoiceAnswer(
                    choice="TYPE_TEXT", probabilities={"TYPE_TEXT": 1.0, "TAP": 0.0}
                ),
                "text": ChoiceAnswer(choice="t1", probabilities={"t1": 1.0, "none": 0.0}),
            }
        ]
    )
    ctx = RunContext(
        provider,
        Task(goal="Enter the supplied name", allowed_texts=["Blue moon"]),
        RunConfig(mode="grid", screen=SCREEN),
    )
    ctx.history[:] = history
    subjects: list[JsonValue] = []

    def locate(
        context: RunContext,
        state: JsonValue,
        regions: list[Cell],
        images: tuple[str, ...],
        *,
        fine: bool,
    ) -> tuple[Cell, float]:
        assert context is ctx and images
        assert isinstance(state, dict)
        subjects.append(state.get("localization_subject"))
        return regions[0], 0.99

    monkeypatch.setattr(grid, "locate", locate)
    planned = grid.plan(ctx, png())
    assert all(request.images for request in provider.requests)
    if needs_focus:
        assert planned.action.operation == "TAP" and planned.action.point is not None
        assert planned.action.text is None and planned.text_focus_key == "t1"
        assert len(subjects) == 2 and subjects[0] == subjects[1]
        assert "Blue moon" in str(subjects[0])
    else:
        assert planned.action.operation == "TYPE_TEXT" and planned.action.text == "Blue moon"
        assert not subjects


def test_localized_app_change_is_detected_but_sparse_caret_is_ignored() -> None:
    def image(box: tuple[int, int, int, int]) -> bytes:
        picture = Image.new("RGB", (400, 800), "white")
        ImageDraw.Draw(picture).rectangle(box, fill="black")
        stream = io.BytesIO()
        picture.save(stream, format="PNG")
        return stream.getvalue()

    assert changed(png(), image((100, 200, 130, 230)), tolerance=1.5)
    assert not changed(png(), image((100, 200, 101, 212)), tolerance=1.5)


def test_grid_localization_questions_preserve_the_selected_visual_subject() -> None:
    region = Cell("A1", 0.0, 0.0, 100.0, 100.0)
    provider = ScriptedProvider(
        answers=[
            {
                "inside_A1": NoulAnswer(noul=0.9),
                "fills_A1": NoulAnswer(noul=0.5),
            }
        ]
    )
    ctx = RunContext(provider, Task(goal="Enter a name"), RunConfig(mode="grid", screen=SCREEN))
    subject = "The editable field requiring the approved literal, not the final submit button."
    winner, belief = grid.locate(
        ctx, {"localization_subject": subject}, [region], ("synthetic image",), fine=True
    )
    assert winner is region and belief == 0.9
    assert all(
        subject in question.instructions for question in provider.requests[0].questions.values()
    )
