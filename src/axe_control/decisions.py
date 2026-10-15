"""Typed judgments shared by hosted and locally served decision providers."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

Probability = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
Nonnegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Count = Annotated[int, Field(ge=0)]


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class NoulQuestion(StrictModel):
    type: Literal["noul"] = "noul"
    instructions: str


class ChoiceQuestion(StrictModel):
    type: Literal["choice"] = "choice"
    instructions: str
    criteria: Annotated[dict[str, str], Field(min_length=2, max_length=64)]


class ScoreQuestion(StrictModel):
    type: Literal["score"] = "score"
    instructions: str
    criteria: Annotated[list[str], Field(min_length=2, max_length=64)]


class BoxQuestion(StrictModel):
    type: Literal["box"] = "box"
    instructions: str


Question = Annotated[
    NoulQuestion | ChoiceQuestion | ScoreQuestion | BoxQuestion, Field(discriminator="type")
]


class NoulAnswer(StrictModel):
    type: Literal["noul"] = "noul"
    noul: Probability


class ChoiceAnswer(StrictModel):
    type: Literal["choice"] = "choice"
    choice: str
    probabilities: dict[str, Probability]
    confidence: Probability | None = None


class ScoreAnswer(StrictModel):
    type: Literal["score"] = "score"
    score: Nonnegative
    probabilities: dict[str, Probability]
    legend: dict[str, str]
    confidence: Probability | None = None


class NormalizedBox(StrictModel):
    top: Probability
    bottom: Probability
    left: Probability
    right: Probability

    @model_validator(mode="after")
    def ordered_edges(self) -> Self:
        if self.left >= self.right or self.top >= self.bottom:
            raise ValueError("Box edges must satisfy left < right and top < bottom")
        return self


class BoxAnswer(StrictModel):
    type: Literal["box"] = "box"
    box: NormalizedBox
    confidence: Probability


Answer = Annotated[NoulAnswer | ChoiceAnswer | ScoreAnswer | BoxAnswer, Field(discriminator="type")]


class DecisionRequest(StrictModel):
    state: JsonValue
    questions: Annotated[dict[str, Question], Field(min_length=1, max_length=256)]
    images: tuple[str, ...] = Field(default=(), exclude=True, repr=False)
    reuse_prefix: bool = True


class ProviderIdentity(StrictModel):
    name: str
    requested_model: str
    resolved_model: str | None = None
    resolved_provider: str | None = None
    endpoint: str
    local: bool


class Capabilities(StrictModel):
    decisions: bool
    generation: bool
    vision: bool
    boxes: bool = False
    max_questions: int = Field(ge=1, le=256)
    max_choices: int = Field(ge=2, le=64)


class ProviderUsage(StrictModel):
    request_ms: Nonnegative
    input_tokens: Count | None = None
    output_tokens: Count | None = None
    reported_cost_usd: Nonnegative | None = None
    native_ms: Nonnegative | None = None
    prefill_ms: Nonnegative | None = None
    decode_ms: Nonnegative | None = None
    queue_ms: Nonnegative | None = None
    cache_hit: bool | None = None
    image_tokens: Count | None = None
    backend_allocated_bytes: Count | None = None
    backend_budget_bytes: Count | None = None
    prefix_processed_tokens: Count | None = None
    prefix_reused_tokens: Count | None = None
    context_evictions: Count | None = None


class DecisionReply(StrictModel):
    answers: dict[str, Answer]
    identity: ProviderIdentity
    usage: ProviderUsage


class ModelCall(StrictModel):
    kind: Literal["decision", "generative"]
    succeeded: bool
    identity: ProviderIdentity
    usage: ProviderUsage


class ProviderError(RuntimeError):
    """Provider failure with a safe message, never an HTTP body or input value."""
