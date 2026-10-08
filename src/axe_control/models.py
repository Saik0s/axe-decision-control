"""Tasks, bounded native actions, configuration and content-free telemetry."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, FiniteFloat, JsonValue, model_validator

from .decisions import (
    ModelCall,
    Nonnegative,
    Probability,
    ProviderIdentity,
    ProviderUsage,
    StrictModel,
)

Mode = Literal["direct", "tree", "grid"]
Operation = Literal["TAP", "TYPE_TEXT", "SCROLL_UP", "SCROLL_DOWN", "WAIT", "DONE"]


class Point(StrictModel):
    x: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    y: Annotated[float, Field(ge=0, allow_inf_nan=False)]


class ScreenSize(StrictModel):
    width: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    height: Annotated[float, Field(gt=0, allow_inf_nan=False)]


class Task(StrictModel):
    goal: Annotated[str, Field(min_length=1, max_length=8192)] = Field(repr=False)
    allowed_texts: list[Annotated[str, Field(max_length=2048)]] = Field(
        default_factory=list, repr=False
    )


class Action(StrictModel):
    operation: Operation
    target_ref: str | None = None
    point: Point | None = None
    text: Annotated[str, Field(max_length=2048)] | None = Field(default=None, repr=False)
    replace: bool = True

    @model_validator(mode="after")
    def validate_arguments(self) -> Self:
        if self.operation == "TAP":
            if (self.target_ref is None) == (self.point is None):
                raise ValueError("TAP needs exactly one target reference or point")
            if self.text is not None:
                raise ValueError("TAP must not contain text")
        elif self.operation == "TYPE_TEXT":
            if self.text is None or self.point is not None:
                raise ValueError("TYPE_TEXT needs text and may have a target reference")
        elif self.target_ref is not None or self.point is not None or self.text is not None:
            raise ValueError("This operation does not take a target or text")
        return self


class AgentRequest(StrictModel):
    state: JsonValue
    images: tuple[str, ...] = Field(default=(), exclude=True, repr=False)
    max_output_tokens: int = Field(default=512, ge=64, le=4096)


class AgentReply(StrictModel):
    action: Action
    identity: ProviderIdentity
    usage: ProviderUsage


class RunConfig(StrictModel):
    mode: Mode
    max_steps: int = Field(default=20, ge=1, le=100)
    max_requests: int = Field(default=120, ge=1, le=1000)
    max_seconds: int = Field(default=300, ge=1, le=3600)
    minimum_done: Probability = 0.90
    minimum_inside: Probability = 0.50
    screen: ScreenSize | None = None
    settle_seconds: Nonnegative = 0.35
    grid_columns: int = Field(default=4, ge=2, le=8)
    grid_rows: int = Field(default=8, ge=2, le=16)
    fine_columns: int = Field(default=4, ge=2, le=8)
    fine_rows: int = Field(default=4, ge=2, le=8)
    image_change_tolerance: Nonnegative = 1.5


class ActionHistory(StrictModel):
    operation: Operation
    target_ref: str | None = None
    point: Point | None = None
    text_focus_key: str | None = None
    changed: bool | None = None


class PlannedAction(StrictModel):
    action: Action
    completion_belief: Probability | None = None
    inside_belief: Probability | None = None
    text_focus_key: str | None = None


class Event(StrictModel):
    step: int
    phase: Literal["observe", "decide", "freshness", "act", "verify"]
    at_seconds: Nonnegative
    operation: Operation | None = None
    completion_belief: Probability | None = None
    inside_belief: Probability | None = None
    state_changed: bool | None = None
    text_focus_required: bool = False


class RunReport(StrictModel):
    mode: Mode
    status: Literal["completed", "blocked", "budget_exhausted", "cancelled", "failed"]
    reason: str
    steps: int
    native_commands: int
    native_failures: int
    native_mutations: int
    decision_requests: int
    generative_requests: int
    elapsed_seconds: Nonnegative
    model_seconds: Nonnegative
    reported_cost_usd: Nonnegative | None
    unpriced_requests: int
    identity: ProviderIdentity
    events: list[Event]
    calls: list[ModelCall]


class Frame(StrictModel):
    x: FiniteFloat
    y: FiniteFloat
    width: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    height: Annotated[float, Field(ge=0, allow_inf_nan=False)]

    def center(self) -> Point:
        return Point(x=self.x + self.width / 2, y=self.y + self.height / 2)
