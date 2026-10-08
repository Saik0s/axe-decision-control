"""The model must be able to see every point referenced by a grid question."""

from __future__ import annotations

import base64
import io
import math

import pytest
from PIL import Image

from axe_control.grid import Cell, annotated, cells, data_url


def encoded_image(image: Image.Image) -> Image.Image:
    encoded = data_url(image).split(",", 1)[1]
    with Image.open(io.BytesIO(base64.b64decode(encoded))) as decoded:
        return decoded.convert("RGB")


def visible_markers(image: Image.Image, regions: list[Cell], bounds: Cell) -> int:
    visible = 0
    for region in regions:
        x, y = region.center
        x = (x - bounds.left) * image.width / (bounds.right - bounds.left)
        y = (y - bounds.top) * image.height / (bounds.bottom - bounds.top)
        center = image.crop((round(x), round(y), round(x) + 1, round(y) + 1))
        pixels = center.tobytes()
        colors = zip(pixels[0::3], pixels[1::3], pixels[2::3], strict=True)
        if any(red > 170 and green < 100 and blue < 120 for red, green, blue in colors):
            visible += 1
    return visible


@pytest.mark.parametrize(
    ("pixels", "coarse_shape", "fine_shape"),
    [((1206, 2622), (4, 8), (4, 4)),
     ((750, 1334), (3, 5), (4, 4)),
     ((640, 1136), (8, 16), (8, 8))],
)
@pytest.mark.parametrize("crop", [False, True])
def test_fine_tap_markers_survive_labels_and_transport_resize(
    pixels: tuple[int, int],
    coarse_shape: tuple[int, int],
    fine_shape: tuple[int, int],
    crop: bool,
) -> None:
    source = Image.new("RGB", pixels, "white")
    full = Cell("screen", 0, 0, pixels[0], pixels[1])
    coarse = cells((full.left, full.top, full.right, full.bottom), *coarse_shape)
    selected = coarse[len(coarse) // 2]
    fine = cells((selected.left, selected.top, selected.right, selected.bottom), *fine_shape)
    output = annotated(source, fine, crop=selected if crop else None)
    bounds = selected if crop else full
    assert visible_markers(output, fine, bounds) == len(fine)
    assert visible_markers(encoded_image(output), fine, bounds) == len(fine)


def test_fine_labels_do_not_erase_context_outside_the_refined_region() -> None:
    source = Image.new("RGB", (1206, 2622), (60, 60, 60))
    selected = cells((0, 0, 1206, 2622), 4, 8)[16]
    fine = cells((selected.left, selected.top, selected.right, selected.bottom), 4, 4)
    output = annotated(source, fine)
    outside = output.crop((math.ceil(selected.right) + 2, math.ceil(selected.top),
                           source.width, math.floor(selected.bottom)))
    pixels = outside.tobytes()
    colors = zip(pixels[0::3], pixels[1::3], pixels[2::3], strict=True)
    assert not any(red == green == blue == 255 for red, green, blue in colors)
