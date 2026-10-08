"""Observe, decide, check freshness, act, and verify under shared budgets."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Literal

from .context import BudgetExceeded, Cancelled, RunContext
from .decisions import ProviderError
from .grid import changed
from .models import ActionHistory, Event, Operation, RunConfig, RunReport, Task
from .native import NativeError, NativeTransport
from .policies import direct, grid, tree
from .providers.base import Provider


def run(
    provider: Provider,
    transport: NativeTransport,
    task: Task,
    config: RunConfig,
    *,
    cancellation: threading.Event | None = None,
    on_event: Callable[[Event], None] | None = None,
) -> RunReport:
    ctx = RunContext(provider, task, config, cancellation)
    events: list[Event] = []
    status: Literal["completed", "blocked", "budget_exhausted", "cancelled", "failed"] = (
        "budget_exhausted"
    )
    reason = "Step budget exhausted"
    steps = 0
    stale = 0
    completion_stale = 0
    unchanged = 0
    first_commands, first_failures, first_mutations = (
        transport.commands,
        transport.failures,
        transport.mutations,
    )

    def event(
        phase: Literal["observe", "decide", "freshness", "act", "verify"],
        *,
        operation: Operation | None = None,
        completion_belief: float | None = None,
        inside_belief: float | None = None,
        state_changed: bool | None = None,
        text_focus_required: bool = False,
    ) -> None:
        # Only numeric metrics, bounded operation names and beliefs leave the loop.
        item = Event(
            step=steps,
            phase=phase,
            at_seconds=ctx.elapsed,
            operation=operation,
            completion_belief=completion_belief,
            inside_belief=inside_belief,
            state_changed=state_changed,
            text_focus_required=text_focus_required,
        )
        events.append(item)
        if on_event is not None:
            on_event(item)

    try:
        capabilities = provider.capabilities
        if (
            (config.mode == "direct" and not capabilities.generation)
            or (config.mode != "direct" and not capabilities.decisions)
            or (config.mode == "grid" and not capabilities.vision)
        ):
            raise ValueError("The selected provider does not support this control mode")
        if len(task.allowed_texts) + 1 > provider.capabilities.max_choices:
            raise ValueError("Literal catalog exceeds the selected model's choice capacity")
        if config.mode == "grid" and config.screen is None:
            raise ValueError("Grid mode requires supplied simulator point geometry")
        for step in range(1, config.max_steps + 1):
            steps = step
            ctx.check()
            event("observe")
            ctx.check()
            snapshot = None
            image = None
            if config.mode == "grid":
                image = transport.screenshot()
                planned = grid.plan(ctx, image)
            else:
                snapshot = transport.tree()
                planned = (
                    direct.plan(ctx, snapshot)
                    if config.mode == "direct"
                    else tree.plan(ctx, snapshot)
                )
            action = planned.action
            event(
                "decide",
                operation=action.operation,
                completion_belief=planned.completion_belief,
                inside_belief=planned.inside_belief,
                text_focus_required=planned.text_focus_key is not None,
            )
            ctx.check()
            event("freshness", operation=action.operation)
            ctx.check()
            fresh_snapshot = None
            fresh_image = None
            if image is not None:
                fresh_image = transport.screenshot()
                stale_state = changed(image, fresh_image, tolerance=config.image_change_tolerance)
            elif snapshot is not None:
                fresh_snapshot = transport.tree()
                stale_state = fresh_snapshot.digest != snapshot.digest
            else:
                raise ValueError("Observation is unavailable")
            if stale_state:
                stale += 1
                if stale >= 3:
                    status, reason = "blocked", "Observation changed during three decisions"
                    break
                continue
            stale = 0
            if action.operation == "DONE":
                if config.mode == "grid" and fresh_image is not None:
                    belief = grid.completion(ctx, fresh_image)
                elif config.mode == "direct" and fresh_snapshot is not None:
                    verified = direct.plan(ctx, fresh_snapshot, verify=True)
                    belief = 1.0 if verified.action.operation == "DONE" else 0.0
                elif fresh_snapshot is not None:
                    belief = tree.completion(ctx, fresh_snapshot)
                else:
                    raise ValueError("Completion observation is unavailable")
                ctx.check()
                if fresh_image is not None:
                    verification_changed = changed(
                        fresh_image,
                        transport.screenshot(),
                        tolerance=config.image_change_tolerance,
                    )
                elif fresh_snapshot is not None:
                    verification_changed = transport.tree().digest != fresh_snapshot.digest
                else:
                    raise ValueError("Completion observation is unavailable")
                event(
                    "verify",
                    operation="DONE",
                    completion_belief=belief if config.mode != "direct" else None,
                    state_changed=verification_changed,
                )
                ctx.check()
                if verification_changed:
                    completion_stale += 1
                    if completion_stale >= 3:
                        status, reason = "blocked", "Observation changed during three confirmations"
                        break
                    continue
                if belief >= config.minimum_done:
                    status, reason = "completed", "Model confirmed the goal in a fresh observation"
                else:
                    status, reason = (
                        "blocked",
                        "Fresh completion judgment is below the configured threshold",
                    )
                break
            if planned.inside_belief is not None and planned.inside_belief < config.minimum_inside:
                status, reason = "blocked", "Grid tap belief is below the configured threshold"
                break
            if action.target_ref is not None and fresh_snapshot is not None:
                target = fresh_snapshot.resolve(action.target_ref)
                if action.operation == "TYPE_TEXT" and target.role not in {
                    "TextField",
                    "SecureTextField",
                }:
                    raise ValueError("Text entry target is not an editable field")
            ctx.check()
            event("act", operation=action.operation)
            ctx.check()
            transport.act(action, fresh_snapshot)
            ctx.check()
            if fresh_image is not None:
                state_changed = changed(
                    fresh_image,
                    transport.screenshot(),
                    tolerance=config.image_change_tolerance,
                )
            elif fresh_snapshot is not None:
                state_changed = transport.tree().digest != fresh_snapshot.digest
            else:
                raise ValueError("Post-action observation is unavailable")
            event("verify", operation=action.operation, state_changed=state_changed)
            ctx.history.append(
                ActionHistory(
                    operation=action.operation,
                    target_ref=action.target_ref,
                    point=action.point,
                    text_focus_key=planned.text_focus_key,
                    changed=state_changed,
                )
            )
            unchanged = 0 if state_changed else unchanged + 1
            if unchanged >= 3:
                status, reason = "blocked", "Three actions produced no observable change"
                break
    except BudgetExceeded as error:
        status, reason = "budget_exhausted", str(error)
    except Cancelled as error:
        status, reason = "cancelled", str(error)
    except (ProviderError, NativeError) as error:
        status, reason = "failed", str(error)
    except ValueError:
        status, reason = "blocked", "Invalid policy output or unsupported configuration"
    calls = provider.calls[ctx.first_call :]
    priced = [call.usage.reported_cost_usd for call in calls]
    return RunReport(
        mode=config.mode,
        status=status,
        reason=reason,
        steps=steps,
        native_commands=transport.commands - first_commands,
        native_failures=transport.failures - first_failures,
        native_mutations=transport.mutations - first_mutations,
        decision_requests=sum(call.kind == "decision" for call in calls),
        generative_requests=sum(call.kind == "generative" for call in calls),
        elapsed_seconds=ctx.elapsed,
        model_seconds=sum(call.usage.request_ms for call in calls) / 1000,
        reported_cost_usd=sum(cost for cost in priced if cost is not None)
        if any(cost is not None for cost in priced)
        else None,
        unpriced_requests=sum(cost is None for cost in priced),
        identity=provider.identity,
        events=events,
        calls=list(calls),
    )
