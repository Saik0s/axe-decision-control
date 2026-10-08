from __future__ import annotations

from ..context import RunContext
from ..decisions import (
    ChoiceAnswer,
    ChoiceQuestion,
    DecisionRequest,
    NoulAnswer,
    NoulQuestion,
    Question,
)
from ..models import Action, PlannedAction
from ..observation import TreeSnapshot
from .common import common_state, literal, operation, operation_question, text_question


def completion(ctx: RunContext, snapshot: TreeSnapshot) -> float:
    reply = ctx.decide(
        DecisionRequest(
            state=common_state(ctx, snapshot.state()),
            questions={
                "complete": NoulQuestion(
                    instructions=(
                        "Every condition in the supplied goal is visibly satisfied in this current "
                        "observation, including any requested start, submission or final result."
                    )
                )
            },
        )
    )
    answer = reply.answers["complete"]
    if not isinstance(answer, NoulAnswer):
        raise ValueError("Completion answer has the wrong type")
    return answer.noul


def plan(ctx: RunContext, snapshot: TreeSnapshot) -> PlannedAction:
    limit = ctx.provider.capabilities.max_choices - 1
    candidates = [element for element in snapshot.elements if element.enabled][:limit]
    criteria = {
        "none": "No semantic target",
        **{
            element.ref: f"{element.role}: {element.label}; value={element.value}"
            for element in candidates
        },
    }
    # Result screens often expose no controls; the model must still be able to stop.
    if not candidates:
        criteria["unavailable"] = "No interactive control is exposed"
    target = ChoiceQuestion(
        instructions=(
            "Choose the current semantic target of the next TAP or TYPE_TEXT. For TYPE_TEXT "
            "select its editable field. Use current values to avoid completed changes. "
            "Choose none for scrolling, waiting, or completion."
        ),
        criteria=criteria,
    )
    questions: dict[str, Question] = {"operation": operation_question(tree=True), "target": target}
    if ctx.task.allowed_texts:
        questions["text"] = text_question(ctx)
    reply = ctx.decide(
        DecisionRequest(state=common_state(ctx, snapshot.state()), questions=questions)
    )
    selected = reply.answers["operation"]
    if not isinstance(selected, ChoiceAnswer):
        raise ValueError("Operation answer has the wrong type")
    op = operation(selected.choice)
    if op == "DONE":
        return PlannedAction(
            action=Action(operation=op), completion_belief=completion(ctx, snapshot)
        )
    if op in {"TAP", "TYPE_TEXT"}:
        target_answer = reply.answers["target"]
        if not isinstance(target_answer, ChoiceAnswer) or target_answer.choice in {
            "none",
            "unavailable",
        }:
            raise ValueError("No usable semantic target was selected")
        ref = target_answer.choice
        snapshot.resolve(ref)
        if op == "TYPE_TEXT":
            text = reply.answers.get("text")
            if not isinstance(text, ChoiceAnswer):
                raise ValueError("No approved literal was selected")
            return PlannedAction(
                action=Action(operation=op, target_ref=ref, text=literal(ctx, text))
            )
        return PlannedAction(action=Action(operation=op, target_ref=ref))
    return PlannedAction(action=Action(operation=op))
