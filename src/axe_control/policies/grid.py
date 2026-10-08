from __future__ import annotations

from pydantic import JsonValue

from ..context import RunContext
from ..decisions import (
    ChoiceAnswer,
    DecisionRequest,
    NoulAnswer,
    NoulQuestion,
    Question,
)
from ..grid import Cell, annotated, cells, data_url, open_image
from ..models import Action, PlannedAction
from .common import common_state, literal, operation, operation_question, text_question


def completion(ctx: RunContext, image: bytes) -> float:
    reply = ctx.decide(
        DecisionRequest(
            state=common_state(ctx, "Current screenshot. No accessibility data is available."),
            images=(data_url(open_image(image)),),
            questions={
                "complete": NoulQuestion(
                    instructions=(
                        "Every condition in the supplied goal is visibly satisfied in this current "
                        "screenshot, including any requested start, submission or final result."
                    )
                )
            },
        )
    )
    answer = reply.answers["complete"]
    if not isinstance(answer, NoulAnswer):
        raise ValueError("Completion answer has the wrong type")
    return answer.noul


def locate(
    ctx: RunContext, state: JsonValue, regions: list[Cell], images: tuple[str, ...], *, fine: bool
) -> tuple[Cell, float]:
    if not isinstance(state, dict) or not isinstance(state.get("localization_subject"), str):
        raise ValueError("Grid localization needs an explicit subject")
    subject = state["localization_subject"]
    questions: dict[str, Question] = {}
    for region in regions:
        inside = (
            (
                f"Target: {subject} The red center point of cell {region.key} lies inside "
                "the visible body of that control. A separate heading or label is not the control."
            )
            if fine
            else (
                f"Target: {subject} Cell {region.key} contains the visual center of that control."
            )
        )
        questions[f"inside_{region.key}"] = NoulQuestion(instructions=inside)
        questions[f"fills_{region.key}"] = NoulQuestion(
            instructions=(
                f"Target: {subject} That control occupies more than half of cell {region.key}."
            )
        )
    answers: dict[str, NoulAnswer] = {}
    items = list(questions.items())
    batch = ctx.provider.capabilities.max_questions
    for start in range(0, len(items), batch):
        reply = ctx.decide(
            DecisionRequest(
                state=state,
                questions=dict(items[start : start + batch]),
                images=images,
            )
        )
        for key, answer in reply.answers.items():
            if not isinstance(answer, NoulAnswer):
                raise ValueError("Grid localization answer has the wrong type")
            answers[key] = answer
    winner = max(
        regions,
        key=lambda region: (
            answers[f"inside_{region.key}"].noul
            * (0.75 + 0.25 * answers[f"fills_{region.key}"].noul)
        ),
    )
    return winner, answers[f"inside_{winner.key}"].noul


def plan(ctx: RunContext, image: bytes) -> PlannedAction:
    screenshot = open_image(image)
    state = common_state(ctx, "Current screenshot. Only pixels and grid geometry are supplied.")
    if ctx.config.screen is not None:
        state["screen_points"] = {
            "width": ctx.config.screen.width,
            "height": ctx.config.screen.height,
        }
    questions: dict[str, Question] = {"operation": operation_question(tree=False)}
    if ctx.task.allowed_texts:
        questions["text"] = text_question(ctx)
    reply = ctx.decide(
        DecisionRequest(
            state=state,
            questions=questions,
            images=(data_url(screenshot),),
        )
    )
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
        focused = bool(
            ctx.history
            and ctx.history[-1].operation == "TAP"
            and ctx.history[-1].text_focus_key == text.choice
        )
        if focused:
            return PlannedAction(action=Action(operation=op, text=value))
        # Screenshot text entry needs an explicit focus tap, even with a hidden keyboard.
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
    state["localization"] = (
        "Infer the ONE next interactive control needed for the goal from the visible current "
        "state and history. If a field needs text and is not focused, locate that field. "
        "Otherwise locate the next necessary button or toggle. Ignore already satisfied "
        "settings. Do not change the intended control between coarse and fine judgments."
    )
    if focus_key is None:
        state["localization_subject"] = (
            "The one next interactive control needed for the goal in the visible current state."
        )
    coarse = cells(
        (0.0, 0.0, float(screenshot.width), float(screenshot.height)),
        ctx.config.grid_columns,
        ctx.config.grid_rows,
    )
    coarse_image = data_url(annotated(screenshot, coarse))
    region, _ = locate(ctx, state, coarse, (coarse_image,), fine=False)
    fine = cells(
        (region.left, region.top, region.right, region.bottom),
        ctx.config.fine_columns,
        ctx.config.fine_rows,
    )
    state["selected_coarse_region"] = region.key
    state["localization"] = (
        "Use the full screenshot for context and the enlarged exact selected region for a "
        "safe tap. The intended control is the next one needed for the goal. Select a red "
        "fine-cell center inside that control. Do not target the blue grid or cell labels."
    )
    winner, belief = locate(
        ctx,
        state,
        fine,
        (
            data_url(annotated(screenshot, fine)),
            data_url(annotated(screenshot, fine, crop=region)),
        ),
        fine=True,
    )
    return PlannedAction(
        action=Action(operation="TAP", point=winner.point(screenshot.size, ctx.config.screen)),
        inside_belief=belief,
        text_focus_key=focus_key,
    )
