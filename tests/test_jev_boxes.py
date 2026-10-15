"""Synthetic Jev 1.14 wire and screenshot-geometry regressions; no paid calls."""

from __future__ import annotations

import base64
import json
from io import BytesIO

import httpx
import pytest
from PIL import Image
from pydantic import JsonValue, TypeAdapter, ValidationError

from axe_control.decisions import (
    Answer,
    BoxAnswer,
    BoxQuestion,
    ChoiceAnswer,
    ChoiceQuestion,
    DecisionReply,
    DecisionRequest,
    NormalizedBox,
    NoulAnswer,
    NoulQuestion,
    ProviderError,
    ScoreAnswer,
    ScoreQuestion,
)
from axe_control.providers.base import validate_reply
from axe_control.providers.openrouter import OpenRouterProvider
from axe_control.providers.winnow import WinnowProvider

_MODEL = "typesafe/jev-1.14"
_RESOLVED = "typesafe/jev-1.14-20261014"
_OBJECT: TypeAdapter[dict[str, JsonValue]] = TypeAdapter(dict[str, JsonValue])
_BOX = {"top": 0.87, "bottom": 0.93, "left": 0.07, "right": 0.93}


def _image(size: tuple[int, int] = (320, 320), *, fmt: str = "PNG") -> str:
    with Image.new("RGB", size, "white") as image, BytesIO() as output:
        image.save(output, format=fmt)
        mime = "jpeg" if fmt == "JPEG" else fmt.lower()
        return f"data:image/{mime};base64," + base64.b64encode(output.getvalue()).decode("ascii")


def _request(*, images: tuple[str, ...] | None = None) -> DecisionRequest:
    return DecisionRequest(
        state={"screen": "synthetic screenshot"},
        images=(_image(),) if images is None else images,
        questions={
            "visible": NoulQuestion(instructions="Is the target visible?"),
            "target": BoxQuestion(instructions="Locate the target."),
        },
    )


def _answer() -> dict[str, JsonValue]:
    return {"type": "box", "box": dict(_BOX), "confidence": 0.95}


def _body() -> dict[str, JsonValue]:
    return {
        "model": _RESOLVED, "provider": "TypeSafe",
        "answers": {"visible": {"type": "noul", "noul": 0.96}, "target": _answer()},
        "usage": {"input_tokens": 100, "output_tokens": 0, "cost": 0.0001},
    }


def _capture(body: dict[str, JsonValue], requests: list[httpx.Request]) -> httpx.MockTransport:
    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        # json.dumps also permits malformed peer NaN/Infinity for rejection tests.
        return httpx.Response(200, content=json.dumps(body).encode())

    return httpx.MockTransport(respond)


def _provider(body: dict[str, JsonValue], requests: list[httpx.Request]) -> OpenRouterProvider:
    return OpenRouterProvider(
        _MODEL, api_key="synthetic-key", transport=_capture(body, requests),
    )


def _wire_image(request: httpx.Request) -> Image.Image:
    state = _OBJECT.validate_json(request.content)["state"]
    assert isinstance(state, list) and isinstance(state[1], dict)
    assert state[1]["type"] == "image_url"
    image_url = state[1]["image_url"]
    assert isinstance(image_url, dict)
    url = image_url["url"]
    assert isinstance(url, str) and url.startswith("data:image/png;base64,")
    return Image.open(BytesIO(base64.b64decode(url.split(",", 1)[1], validate=True)))


def test_jev14_serializes_image_box_questions_header_and_dated_identity() -> None:
    requests: list[httpx.Request] = []
    request = _request()
    with _provider(_body(), requests) as provider:
        capabilities = provider.capabilities
        assert capabilities.decisions and capabilities.vision and capabilities.boxes
        assert not capabilities.generation
        reply = provider.decide(request)
        assert len(requests) == 1
        http_request = requests[0]
        assert http_request.method == "POST"
        assert str(http_request.url) == "https://openrouter.ai/api/alpha/decisions"
        assert http_request.headers["TypeSafe-Danger-Zone-Images"] == "true"
        assert http_request.headers["Authorization"] == "Bearer synthetic-key"
        wire = _OBJECT.validate_json(http_request.content)
        assert wire["model"] == _MODEL
        assert wire["questions"] == {
            "visible": {"type": "noul", "instructions": "Is the target visible?"},
            "target": {"type": "box", "instructions": "Locate the target."},
        }
        state = wire["state"]
        assert isinstance(state, list) and len(state) == 2
        assert state[0] == {"type": "text", "text": json.dumps(request.state)}
        assert "images" not in wire and "reuse_prefix" not in wire
        assert reply.identity.requested_model == _MODEL
        assert reply.identity.resolved_model == _RESOLVED
        assert reply.identity.resolved_provider == "TypeSafe"
        answer = reply.answers["target"]
        assert isinstance(answer, BoxAnswer)
        assert answer.box.model_dump() == _BOX and answer.confidence == 0.95
        assert reply.usage.input_tokens == 100 and reply.usage.reported_cost_usd == 0.0001
        assert validate_reply(request, reply) is reply
        assert provider.calls[0].succeeded
        assert "synthetic screenshot" not in provider.calls[0].model_dump_json()


def test_image_header_is_sent_for_noul_and_does_not_leak_to_text_calls() -> None:
    requests: list[httpx.Request] = []
    body = _body()
    body["answers"] = {"visible": {"type": "noul", "noul": 0.96}}
    with _provider(body, requests) as provider:
        for images in [(_image(),), ()]:
            provider.decide(DecisionRequest(
                state="synthetic screen", images=images,
                questions={"visible": NoulQuestion(instructions="Visible?")},
            ))
        assert requests[0].headers["TypeSafe-Danger-Zone-Images"] == "true"
        assert "TypeSafe-Danger-Zone-Images" not in requests[1].headers
        assert _OBJECT.validate_json(requests[1].content)["state"] == "synthetic screen"


@pytest.mark.parametrize("field", ["top", "bottom", "left", "right"])
@pytest.mark.parametrize("value", [-0.01, 1.01, float("nan"), float("inf"), "0.5", True])
def test_box_rejects_nonfinite_out_of_range_and_untyped_edges(field: str, value: JsonValue) -> None:
    box: dict[str, JsonValue] = dict(_BOX)
    box[field] = value
    with pytest.raises(ValidationError):
        NormalizedBox.model_validate(box)
    body = _body()
    body["answers"] = {
        "visible": {"type": "noul", "noul": 0.96},
        "target": {"type": "box", "box": box, "confidence": 0.95},
    }
    with _provider(body, []) as provider:
        with pytest.raises(ProviderError, match="typed validation"):
            provider.decide(_request())
        assert not provider.calls[0].succeeded


@pytest.mark.parametrize("box", [
    {"top": 0.9, "bottom": 0.1, "left": 0.1, "right": 0.9},
    {"top": 0.1, "bottom": 0.9, "left": 0.9, "right": 0.1},
    {"top": 0.5, "bottom": 0.5, "left": 0.1, "right": 0.9},
    {"top": 0.1, "bottom": 0.9, "left": 0.5, "right": 0.5},
    {"top": 0.1, "left": 0.1, "right": 0.9},
])
def test_box_rejects_reversed_empty_and_missing_edges(box: dict[str, float]) -> None:
    body = _body()
    body["answers"] = {
        "visible": {"type": "noul", "noul": 0.96},
        "target": {"type": "box", "box": dict(box), "confidence": 0.95},
    }
    with _provider(body, []) as provider:
        with pytest.raises(ProviderError, match="typed validation"):
            provider.decide(_request())


@pytest.mark.parametrize("confidence", [None, -0.1, 1.1, float("nan"), float("inf"), True, "0.9"])
def test_box_requires_finite_probability_confidence(confidence: JsonValue) -> None:
    answer = _answer()
    if confidence is None:
        answer.pop("confidence")
    else:
        answer["confidence"] = confidence
    body = _body()
    body["answers"] = {"visible": {"type": "noul", "noul": 0.96}, "target": answer}
    with _provider(body, []) as provider:
        with pytest.raises(ProviderError, match="typed validation"):
            provider.decide(_request())


def test_box_accepts_unit_boundaries_and_requires_matching_question_types() -> None:
    full = BoxAnswer(box=NormalizedBox(top=0.0, bottom=1.0, left=0.0, right=1.0), confidence=0.0)
    with _provider(_body(), []) as provider:
        reply = provider.decide(_request())
    reply.answers["target"] = full
    assert validate_reply(_request(), reply).answers["target"] == full
    cases: list[tuple[DecisionRequest, dict[str, Answer]]] = [
        (_request(), {"visible": NoulAnswer(noul=0.5), "target": NoulAnswer(noul=0.5)}),
        (DecisionRequest(state="synthetic", questions={"target": NoulQuestion(instructions="?")}),
         {"target": full}),
    ]
    for request, answers in cases:
        mismatched = DecisionReply(answers=answers, identity=reply.identity, usage=reply.usage)
        with pytest.raises(ProviderError, match="mismatched answer type"):
            validate_reply(request, mismatched)


def test_box_without_image_is_rejected_before_http() -> None:
    requests: list[httpx.Request] = []
    with _provider(_body(), requests) as provider:
        with pytest.raises(ProviderError, match="require an image"):
            provider.decide(_request(images=()))
        assert not requests and not provider.calls


@pytest.mark.parametrize("model", ["cloudflare/clef", "typesafe/jev-1.13", "openai/gpt-4.1-mini"])
def test_other_openrouter_models_reject_boxes_before_http(model: str) -> None:
    requests: list[httpx.Request] = []
    with OpenRouterProvider(
        model, api_key="synthetic-key", transport=_capture(_body(), requests),
    ) as provider:
        assert not provider.capabilities.boxes
        with pytest.raises(ProviderError):
            provider.decide(_request())
        assert not requests and not provider.calls


def test_older_provider_defaults_to_no_boxes_and_rejects_before_http() -> None:
    requests: list[httpx.Request] = []
    with WinnowProvider(transport=_capture(_body(), requests)) as provider:
        assert not provider.capabilities.boxes
        with pytest.raises(ProviderError, match="box"):
            provider.decide(_request())
        assert not requests and not provider.calls


@pytest.mark.parametrize("model", [
    _MODEL, "typesafe/jev-1.14-20261015", "typesafe/jev-1.13-20260917",
])
def test_jev14_rejects_unallowlisted_response_models(model: str) -> None:
    body = _body()
    body["model"] = model
    with _provider(body, []) as provider:
        with pytest.raises(ProviderError, match="model identity"):
            provider.decide(_request())
        assert not provider.calls[0].succeeded


@pytest.mark.parametrize("provider_name", [None, "Cloudflare", "TypeSafe\n"])
def test_jev14_requires_typesafe_response_identity(provider_name: str | None) -> None:
    body = _body()
    if provider_name is None:
        body.pop("provider")
    else:
        body["provider"] = provider_name
    with _provider(body, []) as provider:
        with pytest.raises(ProviderError, match="provider identity"):
            provider.decide(_request())


@pytest.mark.parametrize("size", [(1206, 2622), (100, 100), (20, 60), (256, 256), (1568, 1568)])
def test_jev14_prepares_tall_frames_and_tiny_crops_without_padding(size: tuple[int, int]) -> None:
    requests: list[httpx.Request] = []
    with _provider(_body(), requests) as provider:
        provider.decide(_request(images=(_image(size),)))
    with _wire_image(requests[0]) as image:
        width, height = image.size
        assert 280 <= width <= 1568 and 280 <= height <= 1568
        assert 78400 <= width * height <= 2458624
        assert abs(width - height * size[0] / size[1]) <= 1
        assert image.getpixel((0, 0)) == (255, 255, 255)
        assert image.getpixel((width - 1, height - 1)) == (255, 255, 255)
        if size == (1206, 2622):
            assert image.size == (721, 1568)
        if size == (1568, 1568):
            assert image.size == size


def test_jev14_upscales_documented_size_crop_to_empirical_minimum_side() -> None:
    requests: list[httpx.Request] = []
    with _provider(_body(), requests) as provider:
        provider.decide(_request(images=(_image((278, 394)),)))
    with _wire_image(requests[0]) as image:
        width, height = image.size
        assert min(width, height) >= 280
        assert max(width, height) <= 1568
        assert 78400 <= width * height <= 2458624
        assert abs(width - height * 278 / 394) <= 1


@pytest.mark.parametrize("image", [
    _image((1, 10)), _image((10, 1)), _image(fmt="WEBP"),
    "data:image/png;base64,aW52YWxpZA==", "https://example.com/screenshot.png",
    "data:image/png;base64," + "A" * (6 * 1024 * 1024 + 4),
])
def test_jev14_rejects_impossible_geometry_unsupported_or_unbounded_images(image: str) -> None:
    requests: list[httpx.Request] = []
    with _provider(_body(), requests) as provider:
        with pytest.raises(ProviderError):
            provider.decide(_request(images=(image,)))
        assert not requests and not provider.calls


def test_jpeg_is_reencoded_without_applying_exif_orientation() -> None:
    with Image.new("RGB", (300, 600), "red") as original, BytesIO() as output:
        exif = original.getexif()
        exif[274] = 6
        original.save(output, format="JPEG", exif=exif)
        url = "data:image/jpeg;base64," + base64.b64encode(output.getvalue()).decode("ascii")
    requests: list[httpx.Request] = []
    with _provider(_body(), requests) as provider:
        provider.decide(_request(images=(url,)))
    with _wire_image(requests[0]) as image:
        assert image.format == "PNG" and image.size == (300, 600)
        assert not image.getexif() and not image.info


def test_animated_png_is_rejected_before_http() -> None:
    with (
        Image.new("RGB", (320, 320), "red") as first,
        Image.new("RGB", (320, 320), "blue") as second,
        BytesIO() as output,
    ):
        first.save(
            output, format="PNG", save_all=True, append_images=[second], duration=100, loop=0,
        )
        url = "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")
    requests: list[httpx.Request] = []
    with _provider(_body(), requests) as provider:
        with pytest.raises(ProviderError, match="still image"):
            provider.decide(_request(images=(url,)))
        assert not requests and not provider.calls


def test_png_preparation_preserves_alpha_and_pixel_orientation() -> None:
    with Image.new("RGBA", (320, 320), (0, 0, 255, 64)) as original, BytesIO() as output:
        original.putpixel((0, 0), (255, 0, 0, 255))
        original.save(output, format="PNG")
        url = "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")
    requests: list[httpx.Request] = []
    with _provider(_body(), requests) as provider:
        provider.decide(_request(images=(url,)))
    with _wire_image(requests[0]) as image:
        assert image.mode == "RGBA" and image.size == (320, 320)
        assert image.getpixel((0, 0)) == (255, 0, 0, 255)
        assert image.getpixel((319, 319)) == (0, 0, 255, 64)


@pytest.mark.parametrize("kind", ["choice", "score"])
def test_jev14_retains_two_decimal_probability_rounding(kind: str) -> None:
    body = _body()
    question: ChoiceQuestion | ScoreQuestion
    if kind == "choice":
        question = ChoiceQuestion(instructions="Choose", criteria={"a": "A", "b": "B", "c": "C"})
        answer: dict[str, JsonValue] = {
            "type": "choice", "choice": "a", "probabilities": {"a": 0.33, "b": 0.33, "c": 0.33},
        }
    else:
        question = ScoreQuestion(instructions="Rate", criteria=["A", "B", "C"])
        answer = {
            "type": "score", "score": 1.0, "probabilities": {"0": 0.33, "1": 0.33, "2": 0.33},
            "legend": {"0": "A", "1": "B", "2": "C"},
        }
    body["answers"] = {"result": answer}
    with _provider(body, []) as provider:
        reply = provider.decide(DecisionRequest(state="synthetic", questions={"result": question}))
        result = reply.answers["result"]
        assert isinstance(result, ChoiceAnswer | ScoreAnswer)
        assert sum(result.probabilities.values()) == pytest.approx(1.0)
