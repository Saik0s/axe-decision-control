"""Synthetic wire checks; these never call providers or require live credentials."""

from __future__ import annotations

import json
import logging
import traceback
from collections.abc import Callable
from contextlib import closing
from pathlib import Path

import httpx
import pytest
from pydantic import JsonValue, TypeAdapter

from axe_control.decisions import (
    ChoiceQuestion,
    DecisionRequest,
    NoulQuestion,
    ProviderError,
    ScoreQuestion,
)
from axe_control.models import AgentRequest
from axe_control.providers.base import Provider
from axe_control.providers.openrouter import OpenRouterProvider
from axe_control.providers.winnow import WinnowProvider

_OBJECT: TypeAdapter[dict[str, JsonValue]] = TypeAdapter(dict[str, JsonValue])
_IMAGE = "data:image/png;base64,iVBORw0KGgo="
_KEY = "synthetic-credential-canary"
_STATE = "synthetic-content-canary"
Factory = Callable[[httpx.BaseTransport], Provider]


def _openrouter(transport: httpx.BaseTransport) -> OpenRouterProvider:
    return OpenRouterProvider("cloudflare/clef", api_key=_KEY, transport=transport)


def _winnow(transport: httpx.BaseTransport) -> WinnowProvider:
    return WinnowProvider(api_key=_KEY, transport=transport)


def _generation(transport: httpx.BaseTransport) -> OpenRouterProvider:
    return OpenRouterProvider("openai/gpt-4.1-mini", api_key=_KEY, transport=transport)


def _request(*, images: tuple[str, ...] = ()) -> DecisionRequest:
    return DecisionRequest(
        state={"visible": _STATE}, images=images,
        questions={"ready": NoulQuestion(instructions="Is the synthetic state ready?")},
    )


def _body(model: str = "cloudflare/clef") -> dict[str, JsonValue]:
    return {
        "model": model, "provider": "Cloudflare",
        "answers": {"ready": {"type": "noul", "noul": 0.75}},
        "usage": {"input_tokens": 17, "output_tokens": 0, "cost": 0.001},
        "future_envelope_field": {"ignored": _STATE},
    }


def _chat_body(model: str) -> dict[str, JsonValue]:
    return {
        "model": model, "provider": "Synthetic",
        "choices": [{
            "finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": None,
                "tool_calls": [{
                    "id": "call_synthetic", "type": "function",
                    "function": {
                        "name": "simulator_action",
                        "arguments": json.dumps({"operation": "TAP", "target_ref": "ref-1"}),
                    },
                }],
            },
        }],
        "usage": {"prompt_tokens": 19, "completion_tokens": 8},
    }


def _capture(body: dict[str, JsonValue], requests: list[httpx.Request]) -> httpx.MockTransport:
    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=body)

    return httpx.MockTransport(respond)


def test_clef_images_are_state_content_parts() -> None:
    requests: list[httpx.Request] = []
    with _openrouter(_capture(_body(), requests)) as provider:
        reply = provider.decide(_request(images=(_IMAGE, _IMAGE)))
        wire = _OBJECT.validate_json(requests[0].content)
        assert wire["state"] == [
            {"type": "text", "text": json.dumps({"visible": _STATE})},
            {"type": "image_url", "image_url": {"url": _IMAGE}},
            {"type": "image_url", "image_url": {"url": _IMAGE}},
        ]
        assert "images" not in wire and "reuse_prefix" not in wire
        assert str(requests[0].url) == "https://openrouter.ai/api/alpha/decisions"
        assert requests[0].headers["Authorization"] == "Bearer " + _KEY
        assert reply.identity.resolved_model == "cloudflare/clef"
        assert reply.identity.resolved_provider == "Cloudflare"
        assert reply.usage.input_tokens == 17 and reply.usage.reported_cost_usd == 0.001
        assert len(provider.calls) == 1 and provider.calls[0].succeeded
        assert provider.calls[0].kind == "decision"
        saved = provider.calls[0].model_dump_json()
        assert _STATE not in saved and _KEY not in saved and _IMAGE not in saved
        exposed = provider.identity
        exposed.resolved_model = "caller-change"
        assert provider.identity.resolved_model == "cloudflare/clef"


def test_jev_is_text_only_and_accepts_documented_resolved_version() -> None:
    requests: list[httpx.Request] = []
    body = _body("typesafe/jev-1.13-20260917")
    body.pop("provider")
    with OpenRouterProvider(
        "typesafe/jev-1.13", api_key=_KEY, transport=_capture(body, requests),
    ) as provider:
        assert not provider.capabilities.vision and not provider.capabilities.generation
        with pytest.raises(ProviderError, match="vision"):
            provider.decide(_request(images=(_IMAGE,)))
        with pytest.raises(ProviderError, match="generation"):
            provider.generate(AgentRequest(state=_STATE))
        assert not requests and not provider.calls
        reply = provider.decide(_request())
        assert _OBJECT.validate_json(requests[0].content)["state"] == {"visible": _STATE}
        assert reply.identity.requested_model == "typesafe/jev-1.13"
        assert reply.identity.resolved_model == "typesafe/jev-1.13-20260917"
        assert reply.identity.resolved_provider is None


@pytest.mark.parametrize("factory,encoded_limit", [
    (_openrouter, 6 * 1024 * 1024), (_winnow, 24 * 1024 * 1024),
])
def test_image_bytes_are_bounded_before_post(factory: Factory, encoded_limit: int) -> None:
    requests: list[httpx.Request] = []
    oversized = "data:image/png;base64," + "A" * (encoded_limit + 4)
    with closing(factory(_capture(_body(), requests))) as provider:
        with pytest.raises(ProviderError, match="bounded"):
            provider.decide(_request(images=(oversized,)))
        assert not requests and not provider.calls


def test_winnow_extensions_and_native_metrics_are_mapped_without_logits() -> None:
    body = _body("Winnow-12B")
    body["answers"] = {"ready": {
        "type": "noul", "noul": 0.75,
        "winnow": {"logits": [_STATE], "temperature": 1.0, "future": _STATE},
    }}
    body["winnow"] = {
        "cache_hit": True, "image_tokens": 5, "native_ms": 7.5,
        "prefill_ms": 3.0, "request_prefill_ms": 2.5, "decode_ms": 1.5,
        "queue_ms": 0.5, "backend_allocated_bytes": 1234, "backend_budget_bytes": 5678,
        "prefix_processed_tokens": 0, "prefix_reused_tokens": 12, "context_evictions": 2,
        "question_count": 1, "prefix_tokens": 12, "suffix_tokens": 5, "future": _STATE,
    }
    requests: list[httpx.Request] = []
    with WinnowProvider(
        base_url="http://127.0.0.1:8093", api_key=_KEY, transport=_capture(body, requests),
    ) as provider:
        request = _request(images=(_IMAGE,)).model_copy(update={"reuse_prefix": False})
        reply = provider.decide(request)
        wire = _OBJECT.validate_json(requests[0].content)
        assert str(requests[0].url) == "http://127.0.0.1:8093/v1/systemone"
        assert wire["winnow"] == {"images": [_IMAGE], "diagnostics": True, "reuse_prefix": False}
        assert wire["state"] == {"visible": _STATE} and "images" not in wire
        assert reply.identity.local and reply.identity.resolved_provider == "winnow"
        assert reply.usage.native_ms == 7.5 and reply.usage.prefill_ms == 5.5
        assert reply.usage.decode_ms == 1.5 and reply.usage.queue_ms == 0.5
        assert reply.usage.cache_hit and reply.usage.image_tokens == 5
        assert reply.usage.backend_allocated_bytes == 1234
        assert reply.usage.backend_budget_bytes == 5678
        assert reply.usage.prefix_processed_tokens == 0 and reply.usage.prefix_reused_tokens == 12
        assert reply.usage.context_evictions == 2
        assert "peak" not in reply.usage.model_dump_json()
        assert "winnow" not in reply.answers["ready"].model_dump()
        assert _STATE not in provider.calls[0].model_dump_json()


@pytest.mark.parametrize("image", [
    "/private/image.png", "https://example.com/a.png", "bad", "data:image/png;base64,?",
])
def test_winnow_rejects_invalid_images_before_http(image: str) -> None:
    requests: list[httpx.Request] = []
    with _winnow(_capture(_body("Winnow-12B"), requests)) as provider:
        with pytest.raises(ProviderError):
            provider.decide(_request(images=(image,)))
        assert not requests and not provider.calls


def test_disabled_vision_rejects_both_local_interfaces() -> None:
    requests: list[httpx.Request] = []
    with WinnowProvider(
        vision=False, transport=_capture(_body("Winnow-12B"), requests),
    ) as provider:
        with pytest.raises(ProviderError, match="vision"):
            provider.decide(_request(images=(_IMAGE,)))
        with pytest.raises(ProviderError, match="vision"):
            provider.generate(AgentRequest(state=_STATE, images=(_IMAGE,)))
        assert not requests and not provider.calls


@pytest.mark.parametrize("model,accepted", [
    ("typesafe/jev-1.13", True), ("cloudflare/clef", False),
])
def test_hosted_choice_rounding_is_model_aware(model: str, accepted: bool) -> None:
    body = _body(model)
    if model == "typesafe/jev-1.13":
        body["provider"] = "TypeSafe"
    body["answers"] = {"route": {
        "type": "choice", "choice": "a", "probabilities": {"a": 0.33, "b": 0.33, "c": 0.33},
    }}
    request = DecisionRequest(state=_STATE, questions={"route": ChoiceQuestion(
        instructions="Choose a route", criteria={"a": "A", "b": "B", "c": "C"},
    )})
    with OpenRouterProvider(model, api_key=_KEY, transport=_capture(body, [])) as provider:
        if accepted:
            reply = provider.decide(request)
            answer = reply.answers["route"]
            assert answer.type == "choice"
            assert answer.probabilities == pytest.approx({"a": 1 / 3, "b": 1 / 3, "c": 1 / 3})
        else:
            with pytest.raises(ProviderError, match="probability"):
                provider.decide(request)
        assert provider.calls[0].succeeded == accepted


@pytest.mark.parametrize("value", [-0.1, 1.1, "0.5", True, float("nan"), float("inf")])
@pytest.mark.parametrize("factory,model", [
    (_openrouter, "cloudflare/clef"), (_winnow, "Winnow-12B"),
])
def test_invalid_probabilities_are_rejected(factory: Factory, model: str, value: JsonValue) -> None:
    body = _body(model)
    body["answers"] = {"ready": {"type": "noul", "noul": value}}
    # Non-finite JSON simulates a malformed peer without asking httpx to encode it.
    wire = json.dumps(body).encode()
    attempts: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        return httpx.Response(200, content=wire)

    with closing(factory(httpx.MockTransport(respond))) as provider:
        with pytest.raises(ProviderError, match="typed validation"):
            provider.decide(_request())
        assert len(attempts) == len(provider.calls) == 1
        assert not provider.calls[0].succeeded


@pytest.mark.parametrize("case", [
    "model", "provider", "ids", "answer_type", "extra_answer", "usage_type",
])
@pytest.mark.parametrize("factory,model", [
    (_openrouter, "cloudflare/clef"), (_winnow, "Winnow-12B"),
])
def test_wire_identity_and_answer_contract_failures(
    factory: Factory, model: str, case: str,
) -> None:
    body = _body(model)
    if case == "model":
        body["model"] = "unexpected-model"
    elif case == "provider":
        if model == "Winnow-12B":
            body["winnow"] = {"cache_hit": "true"}
        else:
            body["provider"] = "unsafe\nprovider"
    elif case == "ids":
        body["answers"] = {"wrong": {"type": "noul", "noul": 0.75}}
    elif case == "answer_type":
        body["answers"] = {"ready": {"type": "choice", "choice": "a", "probabilities": {"a": 1.0}}}
    elif case == "extra_answer":
        body["answers"] = {"ready": {"type": "noul", "noul": 0.75, "unknown": _STATE}}
    else:
        body["usage"] = {"input_tokens": "17", "output_tokens": 0}
    with closing(factory(_capture(body, []))) as provider:
        with pytest.raises(ProviderError):
            provider.decide(_request())
        assert len(provider.calls) == 1 and not provider.calls[0].succeeded


@pytest.mark.parametrize("probabilities,choice", [
    ({"a": 0.0, "b": 0.0}, "a"), ({"a": 0.6, "b": 0.1}, "a"),
    ({"a": 0.1, "b": 0.9}, "a"), ({"a": 1.0, "wrong": 0.0}, "a"),
])
def test_winnow_does_not_normalize_invalid_distributions(
    probabilities: dict[str, JsonValue], choice: str,
) -> None:
    body = _body("Winnow-12B")
    body["answers"] = {"route": {
        "type": "choice", "choice": choice, "probabilities": probabilities,
    }}
    request = DecisionRequest(state=_STATE, questions={"route": ChoiceQuestion(
        instructions="Choose a route", criteria={"a": "A", "b": "B"},
    )})
    with _winnow(_capture(body, [])) as provider:
        with pytest.raises(ProviderError):
            provider.decide(request)
        assert provider.calls[0].usage.input_tokens == 17


def test_score_legend_and_expected_value_are_validated() -> None:
    body = _body("Winnow-12B")
    body["answers"] = {"progress": {
        "type": "score", "score": 1.5, "legend": {"0": "None", "1": "Some", "2": "Done"},
        "probabilities": {"0": 0.1, "1": 0.3, "2": 0.6},
    }}
    request = DecisionRequest(state=_STATE, questions={"progress": ScoreQuestion(
        instructions="Rate progress", criteria=["None", "Some", "Done"],
    )})
    with _winnow(_capture(body, [])) as provider:
        assert provider.decide(request).answers["progress"].type == "score"
        body["answers"] = {"progress": {
            "type": "score", "score": 0.1, "legend": {"0": "None", "1": "Some", "2": "Done"},
            "probabilities": {"0": 0.1, "1": 0.3, "2": 0.6},
        }}
        with pytest.raises(ProviderError, match="score"):
            provider.decide(request)
        assert [call.succeeded for call in provider.calls] == [True, False]


@pytest.mark.parametrize("factory,model", [
    (_generation, "openai/gpt-4.1-mini"), (_winnow, "Winnow-12B"),
])
def test_generation_sends_action_schema_and_parses_actual_tool_calls(
    factory: Factory, model: str,
) -> None:
    requests: list[httpx.Request] = []
    with closing(factory(_capture(_chat_body(model), requests))) as provider:
        reply = provider.generate(AgentRequest(
            state=_STATE, images=(_IMAGE,), max_output_tokens=128,
        ))
        wire = _OBJECT.validate_json(requests[0].content)
        expected_path = (
            "/v1/chat/completions" if model == "Winnow-12B" else "/api/v1/chat/completions"
        )
        assert requests[0].url.path == expected_path
        assert wire["max_tokens"] == 128 and wire["parallel_tool_calls"] is False
        assert wire["stream"] is False and "response_format" not in wire
        assert wire["tool_choice"] == (
            "required" if model == "Winnow-12B"
            else {"type": "function", "function": {"name": "simulator_action"}}
        )
        messages = wire["messages"]
        assert isinstance(messages, list) and isinstance(messages[1], dict)
        assert messages[1]["content"] == [
            {"type": "text", "text": json.dumps(_STATE)},
            {"type": "image_url", "image_url": {"url": _IMAGE}},
        ]
        tools = wire["tools"]
        assert isinstance(tools, list) and len(tools) == 1
        tool = tools[0]
        assert isinstance(tool, dict) and tool["type"] == "function"
        function = tool["function"]
        assert isinstance(function, dict) and function["name"] == "simulator_action"
        schema = function["parameters"]
        assert isinstance(schema, dict) and schema["additionalProperties"] is False
        properties = schema["properties"]
        assert isinstance(properties, dict)
        operation = properties["operation"]
        assert isinstance(operation, dict) and operation["enum"] == [
            "TAP", "TYPE_TEXT", "SCROLL_UP", "SCROLL_DOWN", "WAIT", "DONE",
        ]
        assert reply.action.operation == "TAP" and reply.action.target_ref == "ref-1"
        assert reply.usage.input_tokens == 19 and reply.usage.output_tokens == 8
        assert len(provider.calls) == 1 and provider.calls[0].kind == "generative"


@pytest.mark.parametrize("factory,model", [
    (_generation, "openai/gpt-4.1-mini"), (_winnow, "Winnow-12B"),
])
@pytest.mark.parametrize("case", [
    "prose", "wrong_tool", "multiple", "unsafe_action", "unbounded", "truncated",
])
def test_generation_never_falls_back_to_prose(factory: Factory, model: str, case: str) -> None:
    body = _chat_body(model)
    function: dict[str, JsonValue] = {
        "name": "wrong_tool" if case == "wrong_tool" else "simulator_action",
        "arguments": json.dumps({"operation": "SHELL", "text": _STATE})
        if case == "unsafe_action" else json.dumps({"operation": "TAP"})
        if case == "unbounded" else json.dumps({"operation": "DONE"}),
    }
    call: dict[str, JsonValue] = {"id": "call_synthetic", "type": "function", "function": function}
    body["choices"] = [{
        "finish_reason": "length" if case == "truncated" else "stop",
        "message": {"content": '{"operation":"DONE"}', "tool_calls":
            [] if case == "prose" else [call, call] if case == "multiple" else [call]},
    }]
    with closing(factory(_capture(body, []))) as provider:
        with pytest.raises(ProviderError):
            provider.generate(AgentRequest(state=_STATE))
        assert len(provider.calls) == 1 and not provider.calls[0].succeeded


@pytest.mark.parametrize("status", [302, 401, 429, 500, 200, 0])
@pytest.mark.parametrize("factory", [_openrouter, _winnow])
def test_failures_are_counted_once_and_sanitized(
    factory: Factory, status: int,
    caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str],
) -> None:
    attempts: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        if status == 0:
            raise httpx.ConnectError(_KEY + _STATE, request=request)
        return httpx.Response(status, text=_KEY + _STATE, headers={"Location": "/retry"})

    caplog.set_level(logging.DEBUG)
    with closing(factory(httpx.MockTransport(respond))) as provider:
        with pytest.raises(ProviderError) as failure:
            provider.decide(_request())
        rendered = "".join(traceback.format_exception(failure.value))
        assert _KEY not in rendered and _STATE not in rendered
        assert len(attempts) == len(provider.calls) == 1 and not provider.calls[0].succeeded
        assert provider.calls[0].usage.request_ms >= 0
        assert provider.calls[0].identity.resolved_model is None
        output = capsys.readouterr()
        assert _KEY not in caplog.text + output.out + output.err
        assert _STATE not in caplog.text + output.out + output.err


def test_key_file_precedence_and_unset_cost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    key_file = tmp_path / "synthetic-key"
    key_file.write_text(_KEY + "\n", encoding="utf-8")
    monkeypatch.setenv("OPENROUTER_API_KEY", "unused-env-key")
    body = _body()
    body["usage"] = {"input_tokens": 17, "output_tokens": 2}
    requests: list[httpx.Request] = []
    with OpenRouterProvider(
        "cloudflare/clef", api_key_file=key_file, transport=_capture(body, requests),
    ) as provider:
        reply = provider.decide(_request())
        assert requests[0].headers["Authorization"] == "Bearer " + _KEY
        assert reply.usage.reported_cost_usd is None and reply.usage.output_tokens == 2


def test_bad_configuration_and_closed_provider_never_make_requests() -> None:
    requests: list[httpx.Request] = []
    transport = _capture(_body(), requests)
    with pytest.raises(ProviderError):
        OpenRouterProvider("cloudflare/clef", api_key="unsafe\nkey", transport=transport)
    with pytest.raises(ProviderError):
        OpenRouterProvider(
            "cloudflare/clef", api_key=_KEY,
            base_url="https://secret@example.com", transport=transport,
        )
    with _openrouter(transport) as provider:
        provider.close()
        with pytest.raises(ProviderError, match="closed"):
            provider.decide(_request())
        assert not requests and not provider.calls


@pytest.mark.parametrize("base_url", [
    "https://user:password@example.com", "https://example.com?api_key=secret",
    "https://example.com#secret", "file:///private/secret",
])
def test_unsafe_endpoints_are_rejected_by_both_constructors(base_url: str) -> None:
    with pytest.raises(ProviderError):
        OpenRouterProvider("cloudflare/clef", api_key=_KEY, base_url=base_url)
    with pytest.raises(ProviderError):
        WinnowProvider(base_url=base_url)


@pytest.mark.parametrize("factory,model", [
    (_openrouter, "cloudflare/clef"), (_winnow, "Winnow-12B"),
])
def test_clients_ignore_environment_proxy_and_certificate_settings(
    factory: Factory, model: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "invalid-proxy-url")
    monkeypatch.setenv("SSL_CERT_FILE", "/missing/synthetic-certificate")
    with closing(factory(_capture(_body(model), []))) as provider:
        assert provider.decide(_request()).answers["ready"].type == "noul"


@pytest.mark.parametrize("factory,limit", [(_openrouter, 4), (_generation, 4), (_winnow, 16)])
def test_explicit_image_counts_are_bounded_before_post(factory: Factory, limit: int) -> None:
    requests: list[httpx.Request] = []
    with closing(factory(_capture(_body(), requests))) as provider:
        images = (_IMAGE,) * (limit + 1)
        with pytest.raises(ProviderError, match="images"):
            if provider.capabilities.decisions:
                provider.decide(_request(images=images))
            else:
                provider.generate(AgentRequest(state=_STATE, images=images))
        assert not requests and not provider.calls
