"""Bounded still-image preparation for JEV, preserving screenshot geometry."""

from __future__ import annotations

import base64
import math
import struct
import warnings
import zlib
from io import BytesIO

from PIL import Image

from ..decisions import ProviderError

_MAX_ENCODED_BYTES = 6 * 1024 * 1024
_MAX_INPUT_BYTES = 4 * 1024 * 1024
# Retain Pillow's default safety ceiling even if another caller disables its guard.
_MAX_SOURCE_PIXELS = 89_478_485
# OpenRouter rejected a 278-pixel side on 2026-10-15 despite the documented 256 minimum.
# Use a conservative empirical floor; uniform scaling preserves screenshot geometry.
_MIN_SIDE = 280
_MAX_SIDE = 1568
_MIN_AREA = 78_400
_MAX_AREA = 2_458_624


def _decode_data_url(image: str) -> bytes:
    if len(image) > _MAX_ENCODED_BYTES + len("data:image/jpeg;base64,"):
        raise ProviderError("JEV image exceeds the encoded size limit")
    header, separator, encoded = image.partition(",")
    if (
        not separator
        or header not in {"data:image/png;base64", "data:image/jpeg;base64"}
        or not encoded
    ):
        raise ProviderError("JEV requires a PNG or JPEG base64 data URL")
    if len(encoded) > _MAX_ENCODED_BYTES:
        raise ProviderError("JEV image exceeds the encoded size limit")
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except ValueError:
        raise ProviderError("JEV image base64 is invalid") from None
    if len(decoded) > _MAX_INPUT_BYTES:
        raise ProviderError("JEV image exceeds the decoded size limit")
    return decoded


def _valid_dimensions(width: int, height: int) -> bool:
    return (
        _MIN_SIDE <= width <= _MAX_SIDE
        and _MIN_SIDE <= height <= _MAX_SIDE
        and _MIN_AREA <= width * height <= _MAX_AREA
    )


def _dimensions(width: int, height: int) -> tuple[int, int]:
    if width <= 0 or height <= 0 or width * height > _MAX_SOURCE_PIXELS:
        raise ProviderError("JEV image dimensions exceed safe decoding limits")
    lower = max(_MIN_SIDE / width, _MIN_SIDE / height, math.sqrt(_MIN_AREA / (width * height)))
    upper = min(_MAX_SIDE / width, _MAX_SIDE / height, math.sqrt(_MAX_AREA / (width * height)))
    if lower > upper:
        raise ProviderError("JEV image aspect ratio cannot meet dimension limits")
    scale = min(max(1.0, lower), upper)
    target_width, target_height = width * scale, height * scale
    # Check both neighbors: nearest rounding can fall below the minimum area.
    candidates = [
        (candidate_width, candidate_height)
        for candidate_width in {math.floor(target_width), math.ceil(target_width)}
        for candidate_height in {math.floor(target_height), math.ceil(target_height)}
        if _valid_dimensions(candidate_width, candidate_height)
    ]
    if not candidates:
        raise ProviderError("JEV image cannot meet integer dimension limits")
    return min(
        candidates,
        key=lambda size: (
            (size[0] - target_width) ** 2 + (size[1] - target_height) ** 2,
            size,
        ),
    )


def prepare_jev_image(image: str) -> str:
    """Return a metadata-free PNG data URL within JEV's side and area limits.

    Resize uniformly, allowing only integer rounding to change the aspect ratio.
    EXIF orientation is deliberately ignored to preserve screenshot coordinates.
    """
    decoded = _decode_data_url(image)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(decoded), formats=("PNG", "JPEG")) as source:
                if source.format not in {"PNG", "JPEG"}:
                    raise ProviderError("JEV requires a PNG or JPEG image")
                if source.format == "PNG" and (source.is_animated or "loop" in source.info):
                    raise ProviderError("JEV requires a still image")
                size = _dimensions(*source.size)
                source.verify()
            # verify() consumes the decoder; reopen and fully decode before resizing.
            with Image.open(BytesIO(decoded), formats=("PNG", "JPEG")) as source:
                source.load()
                has_alpha = "A" in source.getbands() or "transparency" in source.info
                mode = "RGBA" if has_alpha else "RGB"
                with source.convert(mode) as pixels:
                    with pixels.resize(size, Image.Resampling.LANCZOS) as resized:
                        # A fresh image carries pixels only, including alpha, never EXIF/ICC/text.
                        with Image.new(mode, size) as clean:
                            clean.paste(resized)
                            clean.info.clear()
                            if not _valid_dimensions(*clean.size):
                                raise ProviderError("JEV prepared image exceeds dimension limits")
                            with BytesIO() as output:
                                clean.save(output, format="PNG")
                                encoded = base64.b64encode(output.getvalue()).decode("ascii")
    except (
        OSError,
        ValueError,
        SyntaxError,
        OverflowError,
        MemoryError,
        struct.error,
        zlib.error,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        raise ProviderError("JEV image could not be safely decoded or prepared") from None
    return "data:image/png;base64," + encoded
