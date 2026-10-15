"""OpenRouter decisions and bounded function calls, with content-free accounting."""

from __future__ import annotations

import base64
import json
import math
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Self

import httpx
from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, ValidationError

from ..decisions import (
    Answer,
    BoxQuestion,
    Capabilities,
    Count,
    DecisionReply,
    DecisionRequest,
    ModelCall,
    Nonnegative,
    ProviderError,
    ProviderIdentity,
    ProviderUsage,
    Question,
    ScoreQuestion,
    StrictModel,
)
from ..models import Action, AgentReply, AgentRequest
from .base import validate_reply
from .jev_images import prepare_jev_image

_JEV_BOX_MODEL = "typesafe/jev-1.14"
_DECISION_MODELS = {"cloudflare/clef": 3, "typesafe/jev-1.13": 2, _JEV_BOX_MODEL: 2}
_DECISION_PROVIDERS = {
    "cloudflare/clef": "cloudflare", "typesafe/jev-1.13": "typesafe", _JEV_BOX_MODEL: "typesafe",
}
_RESOLVED_MODELS = {
    "typesafe/jev-1.13": {"typesafe/jev-1.13", "typesafe/jev-1.13-20260917"},
    _JEV_BOX_MODEL: {"typesafe/jev-1.14-20261014"},
}
_JSON: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)


class _Envelope(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")


class _Usage(_Envelope):
    input_tokens: Count | None = None
    output_tokens: Count | None = None
    prompt_tokens: Count | None = None
    completion_tokens: Count | None = None
    cost: Nonnegative | None = None

    def mapped(self, request_ms: float) -> ProviderUsage:
        return ProviderUsage(
            request_ms=request_ms,
            input_tokens=self.input_tokens if self.input_tokens is not None else self.prompt_tokens,
            output_tokens=(
                self.output_tokens if self.output_tokens is not None else self.completion_tokens
            ),
            reported_cost_usd=self.cost,
        )


class _DecisionUsage(_Usage):
    input_tokens: Count
    output_tokens: Count


class _DecisionEnvelope(_Envelope):
    model: str
    provider: str | None = None
    answers: dict[str, Answer] = Field(repr=False)
    usage: _DecisionUsage


class _TextPart(StrictModel):
    type: Literal["text"] = "text"
    text: str = Field(repr=False)


class _ImageURL(StrictModel):
    url: str = Field(repr=False)


class _ImagePart(StrictModel):
    type: Literal["image_url"] = "image_url"
    image_url: _ImageURL = Field(repr=False)


_Part = _TextPart | _ImagePart


class _DecisionPayload(StrictModel):
    model: str
    state: JsonValue | list[_Part] = Field(repr=False)
    questions: dict[str, Question] = Field(repr=False)


class _Message(StrictModel):
    role: Literal["system", "user"]
    content: str | list[_Part] = Field(repr=False)


class _Function(StrictModel):
    name: Literal["simulator_action"] = "simulator_action"
    description: str = "Select exactly one bounded simulator action."
    parameters: JsonValue


class _Tool(StrictModel):
    type: Literal["function"] = "function"
    function: _Function


class _FunctionName(StrictModel):
    name: Literal["simulator_action"] = "simulator_action"


class _ToolChoice(StrictModel):
    type: Literal["function"] = "function"
    function: _FunctionName = Field(default_factory=_FunctionName)


class _ChatPayload(StrictModel):
    model: str
    messages: list[_Message] = Field(repr=False)
    tools: list[_Tool]
    tool_choice: _ToolChoice | Literal["required"] = Field(default_factory=_ToolChoice)
    parallel_tool_calls: Literal[False] = False
    max_tokens: int
    stream: Literal[False] = False


class _CalledFunction(_Envelope):
    name: Literal["simulator_action"]
    arguments: str = Field(repr=False)


class _ToolCall(_Envelope):
    id: str = Field(min_length=1)
    type: Literal["function"]
    function: _CalledFunction


class _ChatMessage(_Envelope):
    tool_calls: list[_ToolCall] = Field(default_factory=list, repr=False)


class _ChatChoice(_Envelope):
    message: _ChatMessage = Field(repr=False)
    finish_reason: str | None = None


class _ChatEnvelope(_Envelope):
    model: str
    provider: str | None = None
    choices: list[_ChatChoice] = Field(repr=False)
    usage: _Usage | None = None


def _parts(state: JsonValue, images: tuple[str, ...]) -> list[_Part]:
    return [
        _TextPart(text=json.dumps(state, ensure_ascii=False, allow_nan=False)),
        *[_ImagePart(image_url=_ImageURL(url=image)) for image in images],
    ]


def _image_size(image: str, *, max_encoded_bytes: int) -> int:
    header, separator, encoded = image.partition(",")
    if (
        not separator or header not in {
            "data:image/png;base64", "data:image/jpeg;base64", "data:image/webp;base64",
        } or not encoded or len(encoded) > max_encoded_bytes
    ):
        raise ProviderError("Provider requires bounded still-image data URLs")
    try:
        return len(base64.b64decode(encoded, validate=True))
    except ValueError:
        raise ProviderError("Provider image data is invalid") from None


def _chat_payload(model: str, request: AgentRequest, *, named_tool: bool = True) -> _ChatPayload:
    content = (
        _parts(request.state, request.images)
        if request.images
        else json.dumps(request.state, ensure_ascii=False, allow_nan=False)
    )
    return _ChatPayload(
        model=model,
        messages=[
            _Message(
                role="system",
                content="Choose one bounded action from the supplied state. "
                "Return exactly one simulator_action function call.",
            ),
            _Message(role="user", content=content),
        ],
        tools=[_Tool(function=_Function(parameters=_JSON.validate_python(Action.model_json_schema())))],
        tool_choice=_ToolChoice() if named_tool else "required",
        max_tokens=request.max_output_tokens,
    )


def _action(body: _ChatEnvelope) -> Action:
    if len(body.choices) != 1:
        raise ProviderError("Provider must return exactly one action choice")
    choice = body.choices[0]
    if choice.finish_reason in {"length", "content_filter", "error"}:
        raise ProviderError("Provider did not finish its action call")
    if len(choice.message.tool_calls) != 1:
        raise ProviderError("Provider must return exactly one simulator_action tool call")
    return Action.model_validate_json(choice.message.tool_calls[0].function.arguments)


def _key(
    api_key: str | None, api_key_file: str | Path | None, prefix: str, *, required: bool
) -> str | None:
    if api_key is not None and api_key_file is not None:
        raise ProviderError("Choose an API key or an API key file")
    if api_key is None:
        key_file = api_key_file or os.environ.get(prefix + "_API_KEY_FILE")
        if key_file is not None:
            try:
                api_key = Path(key_file).read_text(encoding="utf-8").strip()
            except (OSError, UnicodeError):
                raise ProviderError("API key file could not be read") from None
        else:
            api_key = os.environ.get(prefix + "_API_KEY")
    if api_key is not None and (
        not api_key or not api_key.isascii() or any(character.isspace() for character in api_key)
    ):
        raise ProviderError("API key must contain one nonempty token")
    if required and api_key is None:
        raise ProviderError("OpenRouter API key is required")
    return api_key


@dataclass
class _Call:
    identity: ProviderIdentity
    usage: ProviderUsage


class _HTTPProvider:
    """Shared HTTP accounting; provider-specific wire schemas remain in adapters."""

    def __init__(
        self,
        identity: ProviderIdentity,
        api_key: str | None,
        timeout: float,
        transport: httpx.BaseTransport | None,
    ) -> None:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ProviderError("Provider timeout must be finite and positive")
        if not identity.requested_model or any(c.isspace() for c in identity.requested_model):
            raise ProviderError("Provider model must be a nonempty identifier")
        try:
            url = httpx.URL(identity.endpoint)
        except (httpx.InvalidURL, ValueError):
            raise ProviderError("Provider endpoint is invalid") from None
        if (
            url.scheme not in {"http", "https"} or not url.host or url.userinfo
            or url.query or url.fragment
        ):
            raise ProviderError("Provider endpoint must be HTTP without credentials or query")
        self._identity = identity
        self._calls: list[ModelCall] = []
        self._closed = False
        headers = {"Content-Type": "application/json"}
        if api_key is not None:
            headers["Authorization"] = "Bearer " + api_key
        self._client = httpx.Client(
            headers=headers, timeout=timeout, transport=transport, trust_env=False,
            follow_redirects=False,
        )

    @property
    def identity(self) -> ProviderIdentity:
        return self._identity.model_copy(deep=True)

    @property
    def calls(self) -> tuple[ModelCall, ...]:
        return tuple(call.model_copy(deep=True) for call in self._calls)

    @property
    def capabilities(self) -> Capabilities:
        raise NotImplementedError

    def _resolve(self, call: _Call, model: str, provider: str | None) -> None:
        requested = self._identity.requested_model
        if model not in _RESOLVED_MODELS.get(requested, {requested}):
            raise ProviderError("Provider returned a mismatched model identity")
        if provider is not None and not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9 ./_()+-]{0,127}", provider
        ):
            raise ProviderError("Provider returned an invalid provider identity")
        expected_provider = _DECISION_PROVIDERS.get(requested)
        if (
            (requested == _JEV_BOX_MODEL and provider is None)
            or (expected_provider is not None and provider is not None
                and provider.casefold() != expected_provider)
        ):
            raise ProviderError("Provider returned a mismatched provider identity")
        call.identity = call.identity.model_copy(
            update={"resolved_model": model, "resolved_provider": provider}
        )

    def _post[Reply: DecisionReply | AgentReply](
        self,
        endpoint: str,
        payload: StrictModel,
        kind: Literal["decision", "generative"],
        decode: Callable[[bytes, _Call], Reply],
        *,
        headers: dict[str, str] | None = None,
    ) -> Reply:
        if self._closed:
            raise ProviderError("Provider is closed")
        if isinstance(payload, _DecisionPayload) and not self.capabilities.boxes and any(
            isinstance(question, BoxQuestion) for question in payload.questions.values()
        ):
            raise ProviderError("This provider does not support box questions")
        content = payload.model_dump_json(exclude_none=True)
        if len(content.encode("utf-8")) > 32 * 1024 * 1024:
            raise ProviderError("Provider request exceeds the HTTP body limit")
        call = _Call(
            self._identity.model_copy(update={
                "endpoint": endpoint, "resolved_model": None, "resolved_provider": None,
            }),
            ProviderUsage(request_ms=0.0),
        )
        started = time.perf_counter()
        succeeded = False
        try:
            response = self._client.post(endpoint, content=content, headers=headers)
            if not response.is_success:
                raise ProviderError(f"Provider returned HTTP {response.status_code}")
            call.usage.request_ms = (time.perf_counter() - started) * 1000
            reply = decode(response.content, call)
            self._identity = call.identity.model_copy(deep=True)
            succeeded = True
            return reply
        except httpx.HTTPError:
            raise ProviderError("Provider HTTP transport failed") from None
        except (ValidationError, ValueError, TypeError):
            raise ProviderError("Provider response failed typed validation") from None
        finally:
            call.usage.request_ms = (time.perf_counter() - started) * 1000
            self._calls.append(ModelCall(
                kind=kind, succeeded=succeeded, identity=call.identity, usage=call.usage,
            ))

    def close(self) -> None:
        self._client.close()
        self._closed = True

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *arguments: object) -> None:
        self.close()


class OpenRouterProvider(_HTTPProvider):
    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        api_key_file: str | Path | None = None,
        base_url: str = "https://openrouter.ai/api",
        timeout: float = 90,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._decision_url = self._base_url + "/alpha/decisions"
        self._chat_url = self._base_url + "/v1/chat/completions"
        super().__init__(
            ProviderIdentity(
                name="openrouter", requested_model=model, local=False,
                endpoint=self._decision_url if model in _DECISION_MODELS else self._chat_url,
            ),
            _key(api_key, api_key_file, "OPENROUTER", required=True), timeout, transport,
        )

    @property
    def capabilities(self) -> Capabilities:
        decisions = self._identity.requested_model in _DECISION_MODELS
        return Capabilities(
            decisions=decisions, generation=not decisions,
            vision=self._identity.requested_model != "typesafe/jev-1.13",
            boxes=self._identity.requested_model == _JEV_BOX_MODEL,
            max_questions=64 if self._identity.requested_model == "cloudflare/clef" else 256,
            max_choices=64,
        )

    def decide(self, request: DecisionRequest) -> DecisionReply:
        if not self.capabilities.decisions:
            raise ProviderError("This OpenRouter model does not expose typed decisions")
        has_boxes = any(
            isinstance(question, BoxQuestion) for question in request.questions.values()
        )
        if has_boxes and not self.capabilities.boxes:
            raise ProviderError("This OpenRouter model does not support box questions")
        if has_boxes and not request.images:
            raise ProviderError("Box questions require an image")
        if request.images and not self.capabilities.vision:
            raise ProviderError("This OpenRouter decision model does not support vision")
        self._check_images(request.images)
        if not isinstance(request.state, (str, list, dict)):
            raise ProviderError("OpenRouter state must be text, an object or an array")
        if len(request.questions) > self.capabilities.max_questions:
            raise ProviderError("Request exceeds this model's question limit")
        if self._identity.requested_model == "cloudflare/clef" and any(
            isinstance(question, ScoreQuestion) and len(question.criteria) > 10
            for question in request.questions.values()
        ):
            raise ProviderError("Clef accepts at most ten score levels")
        images = request.images
        if self._identity.requested_model == _JEV_BOX_MODEL and images:
            images = tuple(prepare_jev_image(image) for image in images)
            self._check_images(images)
        payload = _DecisionPayload(
            model=self._identity.requested_model,
            state=_parts(request.state, images) if images else request.state,
            questions=request.questions,
        )
        if (
            self._identity.requested_model == "cloudflare/clef"
            and len(payload.model_dump_json().encode("utf-8")) > 13 * 1024 * 1024
        ):
            raise ProviderError("Clef request exceeds the HTTP body limit")

        def decode(content: bytes, call: _Call) -> DecisionReply:
            body = _DecisionEnvelope.model_validate_json(content)
            call.usage = body.usage.mapped(call.usage.request_ms)
            self._resolve(call, body.model, body.provider)
            return validate_reply(
                request,
                DecisionReply(answers=body.answers, identity=call.identity, usage=call.usage),
                rounded_decimals=_DECISION_MODELS[self._identity.requested_model],
            )

        headers = (
            {"TypeSafe-Danger-Zone-Images": "true"}
            if self._identity.requested_model == _JEV_BOX_MODEL and (images or has_boxes) else None
        )
        return self._post(self._decision_url, payload, "decision", decode, headers=headers)

    def _check_images(self, images: tuple[str, ...]) -> None:
        if len(images) > 4:
            raise ProviderError("OpenRouter adapter accepts at most four images")
        total_bytes = 0
        for image in images:
            size = _image_size(image, max_encoded_bytes=6 * 1024 * 1024)
            if size > 4 * 1024 * 1024:
                raise ProviderError("OpenRouter adapter accepts at most 4 MiB per image")
            total_bytes += size
        if total_bytes > 8 * 1024 * 1024:
            raise ProviderError("OpenRouter adapter accepts at most 8 MiB of images")

    def generate(self, request: AgentRequest) -> AgentReply:
        if not self.capabilities.generation:
            raise ProviderError("This OpenRouter decision model does not support generation")
        self._check_images(request.images)

        def decode(content: bytes, call: _Call) -> AgentReply:
            body = _ChatEnvelope.model_validate_json(content)
            if body.usage is not None:
                call.usage = body.usage.mapped(call.usage.request_ms)
            self._resolve(call, body.model, body.provider)
            return AgentReply(action=_action(body), identity=call.identity, usage=call.usage)

        return self._post(
            self._chat_url, _chat_payload(self._identity.requested_model, request),
            "generative", decode,
        )
