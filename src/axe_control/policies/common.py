from __future__ import annotations

from pydantic import JsonValue

from ..context import RunContext
from ..decisions import ChoiceAnswer, ChoiceQuestion, NoulAnswer, ProviderError
from ..models import Operation
from ..observation import JSON

OPERATIONS: dict[str, str] = {
    "TAP": "Tap one necessary control, toggle, or field. Do not toggle an already correct value.",
    "TYPE_TEXT": "Replace the focused editable field with one supplied literal text value.",
    "SCROLL_UP": "Move toward content above the visible region.",
    "SCROLL_DOWN": "Move toward content below the visible region.",
    "WAIT": "Wait briefly for an ongoing UI transition.",
    "DONE": "All requested end conditions are visibly satisfied, including requested activation.",
}


def operation_question(*, tree: bool) -> ChoiceQuestion:
    typing = (
        "TYPE_TEXT also focuses its chosen editable target."
        if tree
        else ("TYPE_TEXT only writes to the already focused field. TAP the field first if needed.")
    )
    return ChoiceQuestion(
        instructions=(
            "Choose the single next action that advances the supplied goal from the current "
            "observation. Consider current values and action history. Do not repeat completed "
            "changes or toggle a correct value. Scroll when a required control is off screen. "
            + typing
        ),
        criteria=OPERATIONS,
    )


def text_question(ctx: RunContext) -> ChoiceQuestion:
    return ChoiceQuestion(
        instructions="Select the supplied literal needed for the next TYPE_TEXT, or none.",
        criteria={
            "none": "No text entry is needed",
            **{f"t{index + 1}": value for index, value in enumerate(ctx.task.allowed_texts)},
        },
    )


def common_state(ctx: RunContext, observation: JsonValue) -> dict[str, JsonValue]:
    return {
        "goal": ctx.task.goal,
        "observation": observation,
        "history": [JSON.validate_json(item.model_dump_json()) for item in ctx.history[-12:]],
    }


def choice(answer: ChoiceAnswer | NoulAnswer, options: dict[str, str]) -> str:
    if not isinstance(answer, ChoiceAnswer) or answer.choice not in options:
        raise ProviderError("Policy received an invalid typed choice")
    return answer.choice


def operation(value: str) -> Operation:
    if value == "TAP":
        return "TAP"
    if value == "TYPE_TEXT":
        return "TYPE_TEXT"
    if value == "SCROLL_UP":
        return "SCROLL_UP"
    if value == "SCROLL_DOWN":
        return "SCROLL_DOWN"
    if value == "WAIT":
        return "WAIT"
    if value == "DONE":
        return "DONE"
    raise ProviderError("Policy received an unknown operation")


def literal(ctx: RunContext, answer: ChoiceAnswer) -> str:
    keys = {f"t{index + 1}": value for index, value in enumerate(ctx.task.allowed_texts)}
    if answer.choice not in keys:
        raise ProviderError("Text operation has no approved literal")
    return keys[answer.choice]
