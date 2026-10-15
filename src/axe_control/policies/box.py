"""Ask Jev for a visible control's normalized boundaries, then tap its center."""
from __future__ import annotations

import math

from ..context import RunContext
from ..decisions import (
    BoxAnswer,
    BoxQuestion,
    DecisionRequest,
    NormalizedBox,
    NoulAnswer,
    NoulQuestion,
    Question,
)
from ..grid import data_url, open_image
from ..models import Action, PlannedAction, Point
from .visual import intent


def plan(ctx: RunContext, image: bytes) -> PlannedAction:
    selected = intent(ctx, image)
    if isinstance(selected, PlannedAction):
        return selected
    state = selected.state
    state["localization"] = (
        "Locate exactly ONE next necessary interactive control for the goal. "
        "Use the current screenshot and history; ignore already satisfied settings. "
        "Return the full visible tappable body, not its separate label or heading."
    )
    subject = state["localization_subject"]
    questions: dict[str, Question] = {
            "present": NoulQuestion(instructions=(
                f"Target: {subject} Is this target visibly present in the current screenshot? "
                "Answer no if the intended control is absent, off screen, or ambiguous."
            )),
            "target": BoxQuestion(instructions=(
                f"The full visible tappable body of this target in the screenshot: {subject} "
                "Return its tight bounds, excluding any separate label. "
                "Locate an enabled control with an unobstructed center, never a covered "
                "or disabled control."
            )),
    }
    screenshot = open_image(image)
    reply = ctx.decide(DecisionRequest(
        state=state, images=(data_url(screenshot),), questions=questions,
    ))
    present, target = reply.answers["present"], reply.answers["target"]
    if not isinstance(present, NoulAnswer) or not isinstance(target, BoxAnswer):
        raise ValueError("Localization answers have the wrong types")
    edges = target.box
    # One bounded closer look, as recommended for experimental image grounding.
    # Do not refine a likely absent target or a highly uncertain localization.
    if present.noul >= 0.5 and target.confidence >= 0.5 and (
        present.noul < ctx.config.minimum_present
        or target.confidence < ctx.config.minimum_box_confidence
    ):
        width, height = screenshot.size
        region = (
            math.floor(max(0.0, edges.left - 0.06) * width),
            math.floor(max(0.0, edges.top - 0.06) * height),
            math.ceil(min(1.0, edges.right + 0.06) * width),
            math.ceil(min(1.0, edges.bottom + 0.06) * height),
        )
        left, top, right, bottom = region
        # Avoid an extreme thin crop that cannot fit image-side limits. Widen
        # the short axis within the original frame; never pad with fake pixels.
        crop_width = min(width, max(right-left, math.ceil((bottom-top) / 4)))
        crop_height = min(height, max(bottom-top, math.ceil((right-left) / 4)))
        left = max(0, min(width-crop_width, math.floor((left+right-crop_width) / 2)))
        top = max(0, min(height-crop_height, math.floor((top+bottom-crop_height) / 2)))
        right, bottom = left+crop_width, top+crop_height
        region = (left, top, right, bottom)
        state["localization"] = (
            "This image is a closer crop of the current screenshot around the candidate. "
            "Locate the same intended control in THIS crop. Return edges relative to THIS "
            "image, not the original screen. Do not change the intended target."
        )
        reply = ctx.decide(DecisionRequest(
            state=state,
            images=(data_url(screenshot.crop(region).resize(((right-left)*2, (bottom-top)*2))),),
            questions=questions,
        ))
        present, target = reply.answers["present"], reply.answers["target"]
        if not isinstance(present, NoulAnswer) or not isinstance(target, BoxAnswer):
            raise ValueError("Refined localization answers have the wrong types")
        edges = NormalizedBox(
            left=(left + target.box.left * (right-left)) / width,
            right=(left + target.box.right * (right-left)) / width,
            top=(top + target.box.top * (bottom-top)) / height,
            bottom=(top + target.box.bottom * (bottom-top)) / height,
        )
    screen = ctx.config.screen
    if screen is None:
        raise ValueError("Box mode requires supplied simulator point geometry")
    return PlannedAction(
        action=Action(operation="TAP", point=Point(
            x=(edges.left + edges.right) * 0.5 * screen.width,
            y=(edges.top + edges.bottom) * 0.5 * screen.height,
        )),
        text_focus_key=selected.text_focus_key,
        box=edges, presence_belief=present.noul, box_confidence=target.confidence,
    )
