"""Shared screenshot intent and completion, without accessibility or fixture state."""
from __future__ import annotations

from dataclasses import dataclass

from pydantic import JsonValue

from ..context import RunContext
from ..decisions import (
    ChoiceAnswer,
    ChoiceQuestion,
    DecisionRequest,
    NoulAnswer,
    NoulQuestion,
    Question,
)
from ..grid import data_url, open_image
from ..models import Action, PlannedAction
from .common import common_state, literal, operation, operation_question, text_question


def completion(ctx: RunContext, image: bytes) -> float:
    reply = ctx.decide(DecisionRequest(
        state=common_state(ctx, "Current screenshot. No accessibility data is available."),
        images=(data_url(open_image(image)),),
        questions={"complete": NoulQuestion(instructions=(
            "Every condition in the supplied goal is visibly satisfied in this current "
            "screenshot, including any requested start, submission or final result."
        ))},
    ))
    answer = reply.answers["complete"]
    if not isinstance(answer, NoulAnswer):
        raise ValueError("Completion answer has the wrong type")
    return answer.noul


@dataclass(frozen=True)
class TapIntent:
    state: dict[str, JsonValue]
    text_focus_key: str | None


def intent(ctx: RunContext, image: bytes) -> TapIntent | PlannedAction:
    state = common_state(ctx, "Current screenshot. Only pixels and geometry are supplied.")
    if ctx.config.screen is not None:
        state["screen_points"] = {
            "width": ctx.config.screen.width, "height": ctx.config.screen.height,
        }
    questions: dict[str, Question] = {"operation": operation_question(tree=False)}
    if ctx.task.allowed_texts:
        questions["text"] = text_question(ctx)
    targets = {f"target{index+1}": value
               for index, value in enumerate(ctx.task.target_descriptions)}
    if ctx.config.mode == "box" and targets:
        questions["target"] = ChoiceQuestion(
            instructions=(
                "Choose the next target for TAP from the caller's workflow descriptions. "
                "Use the screenshot and goal to skip already satisfied steps. "
                "Choose none if the next operation does not need a target."
            ),
            criteria={"none": "No target is needed for the next operation", **targets},
        )
    reply = ctx.decide(DecisionRequest(
        state=state, questions=questions, images=(data_url(open_image(image)),),
    ))
    selected = reply.answers["operation"]
    if not isinstance(selected, ChoiceAnswer):
        raise ValueError("Operation answer has the wrong type")
    op = operation(selected.choice)
    focus_key = None
    if op == "DONE":
        return PlannedAction(action=Action(operation=op), completion_belief=completion(ctx, image))
    if op == "TYPE_TEXT":
        text = reply.answers.get("text")
        if not isinstance(text, ChoiceAnswer):
            raise ValueError("No approved literal was selected")
        value = literal(ctx, text)
        focused = bool(ctx.history and ctx.history[-1].operation == "TAP"
                       and ctx.history[-1].text_focus_key == text.choice)
        if focused:
            return PlannedAction(action=Action(operation=op, text=value))
        focus_key = text.choice
        state["localization_subject"] = (
            f"The editable field that requires the supplied literal {value!r} for the goal. "
            "Locate the input's interactive area, not its separate heading or label."
        )
        op = "TAP"
    if op != "TAP":
        return PlannedAction(action=Action(operation=op))
    if ctx.config.screen is None:
        raise ValueError("Screenshot control requires supplied simulator point geometry")
    if focus_key is None:
        state["localization_subject"] = (
            "The one next interactive control needed for the goal in the visible current state."
        )
        if targets and ctx.config.mode == "box":
            target = reply.answers.get("target")
            if not isinstance(target, ChoiceAnswer) or target.choice not in targets:
                raise ValueError("Tap has no selected caller-described target")
            state["localization_subject"] = targets[target.choice]
    return TapIntent(state, focus_key)
