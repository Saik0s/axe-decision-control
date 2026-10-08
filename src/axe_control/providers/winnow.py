"""Local Winnow decisions, native diagnostics and actual chat function calls."""

from __future__ import annotations

from ipaddress import IPv6Address, ip_address
from pathlib import Path
from typing import Annotated, Literal

import httpx
from pydantic import Field, TypeAdapter

from ..decisions import (
    Answer,
    Capabilities,
    ChoiceAnswer,
    Count,
    DecisionReply,
    DecisionRequest,
    Nonnegative,
    NoulAnswer,
    ProviderError,
    ProviderIdentity,
    ProviderUsage,
    Question,
    ScoreAnswer,
    StrictModel,
)
from ..models import AgentReply, AgentRequest
from .base import validate_reply
from .openrouter import (
    _action,
    _Call,
    _chat_payload,
    _ChatEnvelope,
    _DecisionPayload,
    _DecisionUsage,
    _Envelope,
    _HTTPProvider,
    _image_size,
    _key,
)


class _AnswerDiagnostics(_Envelope):
    temperature: Annotated[float, Field(gt=0, allow_inf_nan=False)] | None = None
    probability_semantics: Literal["conditional_on_answers"] | None = None
    confidence_method: Literal["normalized_inverse_entropy"] | None = None


class _NoulAnswer(NoulAnswer):
    winnow: _AnswerDiagnostics | None = Field(default=None, exclude=True, repr=False)


class _ChoiceAnswer(ChoiceAnswer):
    winnow: _AnswerDiagnostics | None = Field(default=None, exclude=True, repr=False)


class _ScoreAnswer(ScoreAnswer):
    winnow: _AnswerDiagnostics | None = Field(default=None, exclude=True, repr=False)


_WinnowAnswer = Annotated[
    _NoulAnswer | _ChoiceAnswer | _ScoreAnswer, Field(discriminator="type")
]
_ANSWER: TypeAdapter[Answer] = TypeAdapter(Answer)


class _Diagnostics(_Envelope):
    native_ms: Nonnegative | None = None
    prefill_ms: Nonnegative | None = None
    request_prefill_ms: Nonnegative | None = None
    decode_ms: Nonnegative | None = None
    queue_ms: Nonnegative | None = None
    cache_hit: bool | None = None
    image_tokens: Count | None = None
    backend_allocated_bytes: Count | None = None
    backend_budget_bytes: Count | None = None
    prefix_processed_tokens: Count | None = None
    prefix_reused_tokens: Count | None = None
    context_evictions: Count | None = None
    question_count: Count | None = None
    prefix_tokens: Count | None = None
    suffix_tokens: Count | None = None

    def add_to(self, call: _Call) -> None:
        prefill_ms = None
        if self.prefill_ms is not None or self.request_prefill_ms is not None:
            prefill_ms = (self.prefill_ms or 0.0) + (self.request_prefill_ms or 0.0)
        call.usage = ProviderUsage(
            request_ms=call.usage.request_ms, input_tokens=call.usage.input_tokens,
            output_tokens=call.usage.output_tokens,
            reported_cost_usd=call.usage.reported_cost_usd, native_ms=self.native_ms,
            prefill_ms=prefill_ms, decode_ms=self.decode_ms, queue_ms=self.queue_ms,
            cache_hit=self.cache_hit, image_tokens=self.image_tokens,
            backend_allocated_bytes=self.backend_allocated_bytes,
            backend_budget_bytes=self.backend_budget_bytes,
            prefix_processed_tokens=self.prefix_processed_tokens,
            prefix_reused_tokens=self.prefix_reused_tokens,
            context_evictions=self.context_evictions,
        )


class _Usage(_DecisionUsage):
    output_tokens: Annotated[int, Field(ge=0, le=0)]


class _Response(_Envelope):
    model: str
    answers: dict[str, _WinnowAnswer] = Field(repr=False)
    usage: _Usage
    winnow: _Diagnostics | None = None


class _Options(StrictModel):
    diagnostics: Literal[True] = True
    reuse_prefix: bool
    images: tuple[str, ...] = Field(repr=False)


class _Payload(_DecisionPayload):
    questions: dict[str, Question] = Field(repr=False)
    winnow: _Options


def _validate_images(images: tuple[str, ...]) -> None:
    if len(images) > 16:
        raise ProviderError("Winnow accepts at most sixteen images")
    for image in images:
        _image_size(image, max_encoded_bytes=24 * 1024 * 1024)


class WinnowProvider(_HTTPProvider):
    def __init__(
        self,
        model: str = "Winnow-12B",
        base_url: str = "http://127.0.0.1:8091",
        api_key: str | None = None,
        api_key_file: str | Path | None = None,
        vision: bool = True,
        timeout: float = 90,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._decision_url = self._base_url + "/v1/systemone"
        self._chat_url = self._base_url + "/v1/chat/completions"
        self._vision = vision
        super().__init__(
            ProviderIdentity(
                name="winnow", requested_model=model, endpoint=self._decision_url, local=False,
            ),
            _key(api_key, api_key_file, "WINNOW", required=False), timeout, transport,
        )
        host = httpx.URL(self._decision_url).host
        if host.removesuffix(".") == "localhost":
            self._identity.local = True
        else:
            try:
                address = ip_address(host)
                if isinstance(address, IPv6Address) and address.ipv4_mapped is not None:
                    address = address.ipv4_mapped
                self._identity.local = address.is_loopback
            except ValueError:
                self._identity.local = False

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            decisions=True, generation=True, vision=self._vision, max_questions=256, max_choices=64,
        )

    def _check_images(self, images: tuple[str, ...]) -> None:
        if images and not self._vision:
            raise ProviderError("Winnow vision is disabled for this provider")
        _validate_images(images)

    def decide(self, request: DecisionRequest) -> DecisionReply:
        if not isinstance(request.state, (str, list, dict)):
            raise ProviderError("Winnow state must be text, an object or an array")
        self._check_images(request.images)
        payload = _Payload(
            model=self._identity.requested_model, state=request.state, questions=request.questions,
            winnow=_Options(images=request.images, reuse_prefix=request.reuse_prefix),
        )
        if len(payload.model_dump_json().encode("utf-8")) > 32 * 1024 * 1024:
            raise ProviderError("Winnow request exceeds the HTTP body limit")

        def decode(content: bytes, call: _Call) -> DecisionReply:
            body = _Response.model_validate_json(content)
            call.usage = body.usage.mapped(call.usage.request_ms)
            self._resolve(call, body.model, "winnow")
            if body.winnow is not None:
                diagnostics = body.winnow
                diagnostics.add_to(call)
                if (
                    diagnostics.question_count is not None
                    and diagnostics.question_count != len(request.questions)
                ) or (
                    diagnostics.prefix_tokens is not None and diagnostics.suffix_tokens is not None
                    and diagnostics.prefix_tokens + diagnostics.suffix_tokens
                    != body.usage.input_tokens
                ):
                    raise ProviderError("Winnow returned inconsistent usage diagnostics")
            answers = {
                key: _ANSWER.validate_python(answer.model_dump())
                for key, answer in body.answers.items()
            }
            return validate_reply(
                request, DecisionReply(answers=answers, identity=call.identity, usage=call.usage),
            )

        return self._post(self._decision_url, payload, "decision", decode)

    def generate(self, request: AgentRequest) -> AgentReply:
        self._check_images(request.images)

        def decode(content: bytes, call: _Call) -> AgentReply:
            body = _ChatEnvelope.model_validate_json(content)
            if body.usage is not None:
                call.usage = body.usage.mapped(call.usage.request_ms)
            self._resolve(call, body.model, "winnow")
            return AgentReply(action=_action(body), identity=call.identity, usage=call.usage)

        return self._post(
            self._chat_url,
            _chat_payload(self._identity.requested_model, request, named_tool=False),
            "generative", decode,
        )
