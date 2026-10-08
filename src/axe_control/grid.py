"""Grid geometry, annotated model images and screenshot-only freshness checks."""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageStat

from .models import Point, ScreenSize


@dataclass(frozen=True)
class Cell:
    key: str
    left: float
    top: float
    right: float
    bottom: float

    @property
    def center(self) -> tuple[float, float]:
        return ((self.left + self.right) / 2, (self.top + self.bottom) / 2)

    def point(self, pixels: tuple[int, int], screen: ScreenSize) -> Point:
        x, y = self.center
        if not (0 <= x < pixels[0] and 0 <= y < pixels[1]):
            raise ValueError("Grid point lies outside the screenshot")
        return Point(x=x * screen.width / pixels[0], y=y * screen.height / pixels[1])


def cells(bounds: tuple[float, float, float, float], columns: int, rows: int) -> list[Cell]:
    left, top, right, bottom = bounds
    if columns < 2 or rows < 2 or right <= left or bottom <= top:
        raise ValueError("Grid must cover a nonempty region with at least two rows and columns")
    width, height = (right - left) / columns, (bottom - top) / rows
    return [
        Cell(
            key=f"{chr(65 + row)}{column + 1}",
            left=left + column * width,
            top=top + row * height,
            right=left + (column + 1) * width,
            bottom=top + (row + 1) * height,
        )
        for row in range(rows)
        for column in range(columns)
    ]


def open_image(data: bytes) -> Image.Image:
    with Image.open(io.BytesIO(data)) as source:
        return source.convert("RGB")


def data_url(image: Image.Image) -> str:
    resized = image.copy()
    resized.thumbnail((1200, 1800))
    stream = io.BytesIO()
    resized.save(stream, format="PNG")
    return "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode("ascii")


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for location in (
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if Path(location).is_file():
            return ImageFont.truetype(location, size)
    return ImageFont.load_default()


def annotated(image: Image.Image, regions: list[Cell], *, crop: Cell | None = None) -> Image.Image:
    if crop is None:
        result = image.copy()
        offset_x, offset_y, scale = 0.0, 0.0, 1.0
    else:
        result = image.crop((int(crop.left), int(crop.top), int(crop.right), int(crop.bottom)))
        offset_x, offset_y = crop.left, crop.top
        scale = 900 / max(result.size)
        result = result.resize((round(result.width * scale), round(result.height * scale)))
    drawing = ImageDraw.Draw(result)
    fonts: dict[int, ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}
    markers: list[tuple[float, float, float]] = []
    for region in regions:
        box = (
            (region.left - offset_x) * scale,
            (region.top - offset_y) * scale,
            (region.right - offset_x) * scale,
            (region.bottom - offset_y) * scale,
        )
        width, height = box[2] - box[0], box[3] - box[1]
        size = min(round(result.width / 32), int(width / 3), int(height / 3))
        drawing.rectangle(box, outline="#1453e8", width=max(1, size // 10))
        # Dense full-image cells can be too small for a readable label; their crop retains it.
        if size >= 12:
            font = fonts.get(size)
            if font is None:
                font = _font(size)
                fonts[size] = font
            padding = max(1, size // 10)
            left, top, right, bottom = drawing.textbbox((0, 0), region.key, font=font)
            text_width, text_height = right - left, bottom - top
            if text_width + 4 * padding <= width and text_height + 4 * padding <= height:
                x, y = box[0] + padding, box[1] + padding
                drawing.rectangle(
                    (x, y, x + text_width + 2 * padding, y + text_height + 2 * padding),
                    fill="white",
                )
                drawing.text((x + padding - left, y + padding - top), region.key,
                             fill="#1453e8", font=font)
        center_x, center_y = region.center
        center_x, center_y = (center_x - offset_x) * scale, (center_y - offset_y) * scale
        radius = max(2, min(size / 7, width / 4, height / 4))
        markers.append((center_x, center_y, radius))
    # A label or neighboring grid line must never cover the point named by a question.
    for center_x, center_y, radius in markers:
        drawing.ellipse(
            (center_x - radius, center_y - radius, center_x + radius, center_y + radius),
            fill="#e41633",
        )
    return result


def changed(before: bytes, after: bytes, *, tolerance: float) -> bool:
    first, second = open_image(before), open_image(after)
    if first.size != second.size:
        return True
    # Ignore only the status strip. App content and keyboard remain part of freshness.
    crop = (0, round(first.height * 0.06), first.width, first.height)
    first = first.crop(crop).resize((240, 480))
    second = second.crop(crop).resize((240, 480))
    delta = ImageChops.difference(first, second)
    difference = ImageStat.Stat(delta)
    if sum(difference.mean) / len(difference.mean) > tolerance:
        return True
    # A small changed control must not disappear into the full-screen average.
    # Ignore sparse caret/compression noise, while retaining localized text and toggle changes.
    meaningful = delta.convert("L").point(
        lambda value: 255 if value > max(32.0, tolerance * 8) else 0
    )
    return meaningful.histogram()[255] > max(64, round(first.width * first.height * 0.001))
