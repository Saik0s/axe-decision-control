"""Focused synthetic regressions for provider review findings F3 and F4."""

from __future__ import annotations

import json
from random import Random

import httpx
import pytest
from pydantic import JsonValue

from axe_control.decisions import (
    DecisionReply,
    DecisionRequest,
    ProviderError,
    ProviderIdentity,
    ProviderUsage,
    ScoreAnswer,
    ScoreQuestion,
)
from axe_control.providers.base import validate_reply
from axe_control.providers.openrouter import OpenRouterProvider
from axe_control.providers.winnow import WinnowProvider


def _request(levels: int = 3) -> DecisionRequest:
    return DecisionRequest(
        state="synthetic progress",
        questions={"progress": ScoreQuestion(
            instructions="Rate progress",
            criteria=[f"Level {index}" for index in range(levels)],
        )},
    )


def _answer(probabilities: tuple[float, ...], score: float) -> ScoreAnswer:
    return ScoreAnswer(
        score=score,
        probabilities={str(index): value for index, value in enumerate(probabilities)},
        legend={str(index): f"Level {index}" for index in range(len(probabilities))},
        confidence=0.25,
    )


def _reply(answer: ScoreAnswer) -> DecisionReply:
    return DecisionReply(
        answers={"progress": answer},
        identity=ProviderIdentity(
            name="synthetic", requested_model="synthetic",
            endpoint="https://synthetic.example/decisions", local=False,
        ),
        usage=ProviderUsage(request_ms=0.0),
    )


def _body(model: str, answer: ScoreAnswer) -> dict[str, JsonValue]:
    return {
        "model": model,
        "answers": {"progress": {
            "type": "score", "score": answer.score,
            "probabilities": dict(answer.probabilities), "legend": dict(answer.legend),
            "confidence": answer.confidence,
        }},
        "usage": {"input_tokens": 8, "output_tokens": 0},
    }


@pytest.mark.parametrize("base_url,local", [
    ("http://127.0.0.1:8091", True),
    ("http://127.12.34.56:8091", True),
    ("http://[::1]:8091", True),
    ("http://[::ffff:127.0.0.1]:8091", True),
    ("http://localhost:8091", True),
    ("https://LOCALHOST.:8091", True),
    ("https://winnow.example", False),
    ("http://192.168.1.20:8091", False),
    ("http://[fd00::1]:8091", False),
    ("http://[::ffff:192.168.1.20]:8091", False),
    ("http://0.0.0.0:8091", False),
    ("https://localhost.winnow.example", False),
    ("https://127.0.0.1.winnow.example", False),
])
def test_winnow_locality_describes_endpoint_without_http(base_url: str, local: bool) -> None:
    def unexpected_request(request: httpx.Request) -> httpx.Response:
        pytest.fail("Identity inspection must not make HTTP requests")

    with WinnowProvider(
        base_url=base_url, api_key="synthetic-key",
        transport=httpx.MockTransport(unexpected_request),
    ) as provider:
        assert provider.identity.local is local
        assert not provider.calls


@pytest.mark.parametrize("base_url,local", [
    ("http://127.0.0.1:8091", True), ("https://winnow.example", False),
])
def test_winnow_locality_survives_resolution_and_call_accounting(
    base_url: str, local: bool,
) -> None:
    body = _body("Winnow-12B", _answer((0.1, 0.3, 0.6), 1.5))

    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    with WinnowProvider(
        base_url=base_url, api_key="synthetic-key", transport=httpx.MockTransport(respond),
    ) as provider:
        reply = provider.decide(_request())
        assert reply.identity.local is local
        assert provider.identity.local is local
        assert provider.calls[0].identity.local is local
        assert provider.calls[0].succeeded


@pytest.mark.parametrize("decimals,probabilities,score", [
    (3, (0.333, 0.333, 0.333), 1.0),
    (2, (0.33, 0.33, 0.33), 1.0),
    (3, (0.1, 0.3, 0.599), 1.5),
    (3, (0.201, 0.3, 0.5), 1.299),
    (3, (0.1, 0.301, 0.599), 1.498),
    (3, (0.123, 0.877), 0.8774),
    (3, (0.1234, 0.8766), 0.877),
    (3, (1.0, 0.0, 0.0), 0.0),
    (3, (0.0, 0.0, 1.0), 2.0),
])
def test_score_accepts_probability_and_score_rounding(
    decimals: int, probabilities: tuple[float, ...], score: float,
) -> None:
    reply = validate_reply(
        _request(len(probabilities)), _reply(_answer(probabilities, score)),
        rounded_decimals=decimals,
    )
    answer = reply.answers["progress"]
    assert isinstance(answer, ScoreAnswer)
    total = sum(probabilities)
    assert answer.probabilities == pytest.approx({
        str(index): value / total for index, value in enumerate(probabilities)
    })
    assert sum(answer.probabilities.values()) == pytest.approx(1.0)
    assert answer.score == score and answer.confidence == 0.25


@pytest.mark.parametrize("model,probabilities,accepted", [
    ("cloudflare/clef", (0.333, 0.333, 0.333), True),
    ("typesafe/jev-1.13", (0.33, 0.33, 0.33), True),
    ("cloudflare/clef", (0.33, 0.33, 0.33), False),
])
def test_hosted_score_rounding_uses_adapter_precision(
    model: str, probabilities: tuple[float, ...], accepted: bool,
) -> None:
    body = _body(model, _answer(probabilities, 1.0))

    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    with OpenRouterProvider(
        model, api_key="synthetic-key", transport=httpx.MockTransport(respond),
    ) as provider:
        if accepted:
            reply = provider.decide(_request())
            answer = reply.answers["progress"]
            assert isinstance(answer, ScoreAnswer)
            assert answer.probabilities == pytest.approx({"0": 1 / 3, "1": 1 / 3, "2": 1 / 3})
        else:
            with pytest.raises(ProviderError, match="score"):
                provider.decide(_request())
        assert len(provider.calls) == 1 and provider.calls[0].succeeded is accepted


@pytest.mark.parametrize("decimals,probabilities,score", [
    (3, (0.0, 0.0, 0.0), 0.0),
    (3, (0.1, 0.3, 0.5), 1.4),
    (3, (0.333, 0.333, 0.333), 1.01),
    (2, (0.33, 0.33, 0.33), 1.1),
    (3, (0.1, 0.301, 0.599), 1.501),
    (3, (0.1, 0.3, 0.599), 1.4979),
    (3, (0.0, 0.0, 1.0), 2.001),
    (3, (0.0, 1.0), 1.0001),
])
def test_score_rounding_does_not_accept_inconsistent_answers(
    decimals: int, probabilities: tuple[float, ...], score: float,
) -> None:
    with pytest.raises(ProviderError, match="score"):
        validate_reply(
            _request(len(probabilities)), _reply(_answer(probabilities, score)),
            rounded_decimals=decimals,
        )


@pytest.mark.parametrize("case", ["question_ids", "legend", "probability_keys"])
def test_rounded_score_still_requires_exact_ids_and_legend(case: str) -> None:
    answer = _answer((0.333, 0.333, 0.333), 1.0)
    reply = _reply(answer)
    if case == "question_ids":
        reply.answers = {"wrong": answer}
    elif case == "legend":
        answer.legend["2"] = "Wrong level"
    else:
        answer.probabilities["wrong"] = answer.probabilities.pop("2")
    with pytest.raises(ProviderError):
        validate_reply(_request(), reply, rounded_decimals=3)


def test_unrounded_score_keeps_strict_mass_and_expectation_checks() -> None:
    exact = validate_reply(_request(), _reply(_answer((0.1, 0.3, 0.6), 1.5)))
    assert isinstance(exact.answers["progress"], ScoreAnswer)
    for probabilities, score in [
        ((0.333, 0.333, 0.333), 1.0), ((0.1, 0.3, 0.6), 1.5002),
    ]:
        with pytest.raises(ProviderError, match="score"):
            validate_reply(_request(), _reply(_answer(probabilities, score)))


@pytest.mark.parametrize("value", [-0.1, 1.1, float("nan"), float("inf")])
def test_hosted_score_still_rejects_nonfinite_or_out_of_range_probabilities(value: float) -> None:
    answer = _answer((0.1, 0.3, 0.6), 1.5)
    answer.probabilities["0"] = value
    wire = json.dumps(_body("cloudflare/clef", answer)).encode()

    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=wire)

    with OpenRouterProvider(
        "cloudflare/clef", api_key="synthetic-key", transport=httpx.MockTransport(respond),
    ) as provider:
        with pytest.raises(ProviderError, match="typed validation"):
            provider.decide(_request())
        assert len(provider.calls) == 1 and not provider.calls[0].succeeded


@pytest.mark.parametrize("decimals", [2, 3])
@pytest.mark.parametrize("levels", [2, 3, 10, 64])
def test_scores_rounded_from_valid_distributions_remain_valid(decimals: int, levels: int) -> None:
    random = Random(34)
    for _ in range(20):
        weights = [random.random() for _ in range(levels)]
        total = sum(weights)
        probabilities = [value / total for value in weights]
        expected = sum(index * value for index, value in enumerate(probabilities))
        rounded = tuple(round(value, decimals) for value in probabilities)
        reply = validate_reply(
            _request(levels), _reply(_answer(rounded, round(expected, decimals))),
            rounded_decimals=decimals,
        )
        answer = reply.answers["progress"]
        assert isinstance(answer, ScoreAnswer)
        assert sum(answer.probabilities.values()) == pytest.approx(1.0)
