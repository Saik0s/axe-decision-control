"""Boundary localization must stay screenshot-only and gate every native tap."""
from __future__ import annotations

import base64

import pytest
from test_control import ScriptedProvider, ScriptedTransport, png

from axe_control.decisions import Answer, BoxAnswer, ChoiceAnswer, NormalizedBox, NoulAnswer
from axe_control.grid import open_image
from axe_control.models import RunConfig, ScreenSize, Task
from axe_control.runner import run


def localization(*, present: float = 0.99, confidence: float = 0.95) -> dict[str, Answer]:
    return {
        "present": NoulAnswer(noul=present),
        "target": BoxAnswer(
            box=NormalizedBox(left=0.1, right=0.3, top=0.2, bottom=0.4),
            confidence=confidence,
        ),
    }


def provider(answers: list[dict[str, Answer]]) -> ScriptedProvider:
    result = ScriptedProvider(answers=answers)
    result.capabilities = result.capabilities.model_copy(update={"boxes": True})
    return result


def tap() -> dict[str, Answer]:
    return {"operation": ChoiceAnswer(choice="TAP", probabilities={"TAP": 1.0, "DONE": 0.0})}


def test_box_taps_normalized_center_in_logical_points_without_tree_or_oracle() -> None:
    model = provider([tap(), localization()])
    native = ScriptedTransport(forbid_tree=True)
    report = run(model, native, Task(goal="Tap Continue"), RunConfig(
        mode="box", screen=ScreenSize(width=500.0, height=900.0), max_steps=1,
    ))
    assert report.status == "budget_exhausted"
    assert len(native.actions) == 1
    point = native.actions[0].point
    assert point is not None
    assert point.x == pytest.approx(100.0) and point.y == pytest.approx(270.0)
    assert all(request.images for request in model.requests)
    act = next(event for event in report.events if event.phase == "act")
    assert act.box == NormalizedBox(left=0.1, right=0.3, top=0.2, bottom=0.4)
    assert act.tap_point == point and act.presence_belief == 0.99


@pytest.mark.parametrize(("present", "confidence"), [(0.1, 0.99), (0.99, 0.2)])
def test_absent_or_uncertain_target_never_taps_even_with_a_valid_box(
    present: float, confidence: float,
) -> None:
    model = provider([tap(), localization(present=present, confidence=confidence)])
    native = ScriptedTransport(forbid_tree=True)
    report = run(model, native, Task(goal="Tap Continue"), RunConfig(
        mode="box", screen=ScreenSize(width=400.0, height=800.0),
    ))
    assert report.status == "blocked"
    assert "presence or confidence" in report.reason
    assert not native.actions and report.native_mutations == 0


def test_changed_screen_discards_box_without_native_action() -> None:
    class ChangingTransport(ScriptedTransport):
        def screenshot(self) -> bytes:
            self.commands += 1
            return png(change=self.commands % 2 == 0)

    model = provider([tap(), localization()] * 3)
    native = ChangingTransport(forbid_tree=True)
    report = run(model, native, Task(goal="Tap Continue"), RunConfig(
        mode="box", screen=ScreenSize(width=400.0, height=800.0),
    ))
    assert report.status == "blocked" and "changed during three decisions" in report.reason
    assert not native.actions


def test_box_completion_requires_fresh_screenshot_confirmation() -> None:
    model = provider([
        {"operation": ChoiceAnswer(choice="DONE", probabilities={"TAP": 0.0, "DONE": 1.0})},
        {"complete": NoulAnswer(noul=0.99)}, {"complete": NoulAnswer(noul=0.2)},
    ])
    native = ScriptedTransport(forbid_tree=True)
    report = run(model, native, Task(goal="Finish"), RunConfig(
        mode="box", screen=ScreenSize(width=400.0, height=800.0),
    ))
    assert report.status == "blocked" and "completion" in report.reason
    assert report.decision_requests == 3 and not native.actions


def test_unsupported_box_provider_is_refused_before_observation() -> None:
    native = ScriptedTransport(forbid_tree=True)
    report = run(ScriptedProvider(), native, Task(goal="Continue"), RunConfig(
        mode="box", screen=ScreenSize(width=400.0, height=800.0),
    ))
    assert report.status == "blocked" and native.commands == 0


def test_closer_crop_is_mapped_back_to_full_screen_before_tapping() -> None:
    refined: dict[str, Answer] = {
        "present": NoulAnswer(noul=0.99),
        "target": BoxAnswer(box=NormalizedBox(left=0.5, right=0.9, top=0.1, bottom=0.3),
                            confidence=0.95),
    }
    model = provider([tap(), localization(confidence=0.76), refined])
    native = ScriptedTransport(forbid_tree=True)
    report = run(model, native, Task(goal="Tap Continue"), RunConfig(
        mode="box", screen=ScreenSize(width=500.0, height=900.0), max_steps=1,
    ))
    assert len(native.actions) == 1 and report.decision_requests == 3
    point = native.actions[0].point
    assert point is not None
    # Source image 400x800; padded crop is (16,112)-(144,368).
    assert point.x == pytest.approx((16 + 0.7*128) / 400 * 500)
    assert point.y == pytest.approx((112 + 0.2*256) / 800 * 900)
    assert "closer crop" in str(model.requests[-1].state)


def test_uncertain_refined_box_still_cannot_tap() -> None:
    model = provider([tap(), localization(confidence=0.76), localization(confidence=0.76)])
    native = ScriptedTransport(forbid_tree=True)
    report = run(model, native, Task(goal="Tap Continue"), RunConfig(
        mode="box", screen=ScreenSize(width=400.0, height=800.0),
    ))
    assert report.status == "blocked" and not native.actions
    assert report.decision_requests == 3


def test_box_locates_the_model_selected_description_instead_of_a_fixed_sequence() -> None:
    selection = tap()
    selection["target"] = ChoiceAnswer(
        choice="target2", probabilities={"none": 0.0, "target1": 0.0, "target2": 1.0},
    )
    model = provider([selection, localization()])
    native = ScriptedTransport(forbid_tree=True)
    report = run(model, native, Task(goal="Enable Quiet mode",
                 target_descriptions=["Session name field", "Quiet mode toggle"]),
                 RunConfig(mode="box", screen=ScreenSize(width=400.0, height=800.0), max_steps=1))
    assert report.native_mutations == 1
    assert "Quiet mode toggle" in str(model.requests[1].state)
    assert "Session name field" not in str(model.requests[1].state)
    assert "Quiet mode toggle" in model.requests[1].questions["target"].instructions


def test_thin_candidate_refines_without_an_unsupported_image_aspect_ratio() -> None:
    first = localization(confidence=0.76)
    first["target"] = BoxAnswer(
        box=NormalizedBox(left=0.5, right=0.52, top=0.05, bottom=0.95), confidence=0.76,
    )
    model = provider([tap(), first, localization()])
    native = ScriptedTransport(forbid_tree=True)
    report = run(model, native, Task(goal="Tap Continue"), RunConfig(
        mode="box", screen=ScreenSize(width=400.0, height=800.0), max_steps=1,
    ))
    encoded = model.requests[-1].images[0].partition(",")[2]
    image = open_image(base64.b64decode(encoded))
    assert max(image.size) / min(image.size) <= 4
    assert report.native_mutations == 1
