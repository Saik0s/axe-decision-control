from __future__ import annotations

from pydantic import JsonValue

from ..context import RunContext
from ..decisions import (
    DecisionRequest,
    NoulAnswer,
    NoulQuestion,
    Question,
)
from ..grid import Cell, annotated, cells, data_url, open_image
from ..models import Action, PlannedAction
from .visual import intent


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
    selected = intent(ctx, image)
    if isinstance(selected, PlannedAction):
        return selected
    state = selected.state
    focus_key = selected.text_focus_key
    if ctx.config.screen is None:
        raise ValueError("Screenshot control requires supplied simulator point geometry")
    state["localization"] = (
        "Infer the ONE next interactive control needed for the goal from the visible current "
        "state and history. If a field needs text and is not focused, locate that field. "
        "Otherwise locate the next necessary button or toggle. Ignore already satisfied "
        "settings. Do not change the intended control between coarse and fine judgments."
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
