"""Common provider protocol and answer validation."""

from __future__ import annotations

import math
from typing import Protocol

from ..decisions import (
    BoxAnswer,
    BoxQuestion,
    Capabilities,
    ChoiceAnswer,
    ChoiceQuestion,
    DecisionReply,
    DecisionRequest,
    ModelCall,
    NoulAnswer,
    NoulQuestion,
    ProviderError,
    ProviderIdentity,
    ScoreAnswer,
    ScoreQuestion,
)
from ..models import AgentReply, AgentRequest


class Provider(Protocol):
    @property
    def identity(self) -> ProviderIdentity: ...

    @property
    def capabilities(self) -> Capabilities: ...

    @property
    def calls(self) -> tuple[ModelCall, ...]: ...

    def decide(self, request: DecisionRequest) -> DecisionReply: ...

    def generate(self, request: AgentRequest) -> AgentReply: ...

    def close(self) -> None: ...


def _score_bounds(values: list[float], half_unit: float) -> tuple[float, float]:
    lower = [max(0.0, value - half_unit) for value in values]
    upper = [min(1.0, value + half_unit) for value in values]
    remaining = 1.0 - math.fsum(lower)
    if remaining < -1e-6 or math.fsum(upper) < 1.0 - 1e-6:
        raise ProviderError("Provider returned an inconsistent ordered score")
    baseline = math.fsum(index * value for index, value in enumerate(lower))
    bounds: list[float] = []
    # Allocate the remaining unit mass to low/high levels to bound the true expectation.
    for indices in (range(len(values)), range(len(values) - 1, -1, -1)):
        mass = max(0.0, remaining)
        expected = baseline
        for index in indices:
            added = min(mass, upper[index] - lower[index])
            expected += index * added
            mass -= added
        bounds.append(expected)
    return bounds[0], bounds[1]


def validate_reply(
    request: DecisionRequest, reply: DecisionReply, *, rounded_decimals: int | None = None
) -> DecisionReply:
    if reply.answers.keys() != request.questions.keys():
        raise ProviderError("Provider returned mismatched question IDs")
    for key, question in request.questions.items():
        answer = reply.answers[key]
        if isinstance(question, NoulQuestion) and isinstance(answer, NoulAnswer):
            continue
        if isinstance(question, BoxQuestion) and isinstance(answer, BoxAnswer):
            continue
        if isinstance(question, ChoiceQuestion) and isinstance(answer, ChoiceAnswer):
            if (
                set(answer.probabilities) != set(question.criteria)
                or answer.choice not in question.criteria
            ):
                raise ProviderError("Provider returned mismatched choice options")
            total = sum(answer.probabilities.values())
            tolerance = 1e-5
            if rounded_decimals is not None:
                tolerance = len(question.criteria) * 0.5 * 10**-rounded_decimals + 1e-6
            if total <= 0 or abs(total - 1.0) > tolerance:
                raise ProviderError("Provider returned an inconsistent probability distribution")
            probabilities = {
                option: value / total for option, value in answer.probabilities.items()
            }
            if probabilities[answer.choice] + 1e-6 < max(probabilities.values()):
                raise ProviderError("Provider selected a nonwinning option")
            reply.answers[key] = answer.model_copy(update={"probabilities": probabilities})
            continue
        if isinstance(question, ScoreQuestion) and isinstance(answer, ScoreAnswer):
            legend = {str(index): text for index, text in enumerate(question.criteria)}
            if answer.legend != legend or set(answer.probabilities) != set(legend):
                raise ProviderError("Provider returned an inconsistent ordered score")
            total = math.fsum(answer.probabilities.values())
            mass_tolerance = 1e-5
            half_unit = None if rounded_decimals is None else 0.5 * 10**-rounded_decimals
            if half_unit is not None:
                mass_tolerance = len(legend) * half_unit + 1e-6
            if total <= 0 or abs(total - 1.0) > mass_tolerance:
                raise ProviderError("Provider returned an inconsistent ordered score")
            probabilities = {
                index: value / total for index, value in answer.probabilities.items()
            }
            expected = math.fsum(int(index) * value for index, value in probabilities.items())
            minimum = maximum = expected
            score_tolerance = 1e-4
            if half_unit is not None:
                minimum, maximum = _score_bounds(
                    [answer.probabilities[str(index)] for index in range(len(legend))], half_unit,
                )
                score_tolerance = half_unit + 1e-6
            if (
                answer.score > len(legend) - 1
                or answer.score < minimum - score_tolerance
                or answer.score > maximum + score_tolerance
            ):
                raise ProviderError("Provider returned an inconsistent ordered score")
            reply.answers[key] = answer.model_copy(update={"probabilities": probabilities})
            continue
        raise ProviderError("Provider returned a mismatched answer type")
    return reply
