from __future__ import annotations

from ..context import RunContext
from ..models import AgentRequest, PlannedAction
from ..observation import TreeSnapshot
from .common import common_state


def plan(ctx: RunContext, snapshot: TreeSnapshot, *, verify: bool = False) -> PlannedAction:
    state = common_state(ctx, snapshot.state())
    state["allowed_texts"] = list(ctx.task.allowed_texts)
    state["instructions"] = (
        "Return one simulator_action tool call. Use current snapshot references for TAP "
        "and TYPE_TEXT. Leave point null or omitted. TYPE_TEXT focuses its reference and "
        "replaces text. Only use supplied "
        "literal values. Read exposed selected states and values; do not repeat satisfied "
        "changes. Scroll for off-screen controls. DONE requires every goal condition "
        "visibly satisfied after any requested activation."
    )
    if verify:
        state["verification"] = (
            "This is a fresh observation. Independently recheck every end condition."
        )
    reply = ctx.generate(AgentRequest(state=state))
    action = reply.action
    if action.point is not None:
        raise ValueError("Tree baseline must use supplied semantic references")
    if action.target_ref is not None:
        snapshot.resolve(action.target_ref)
    if action.text is not None and action.text not in ctx.task.allowed_texts:
        raise ValueError("Generated text is outside the supplied literal catalog")
    return PlannedAction(action=action)
