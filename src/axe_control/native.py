"""A bounded simulator transport. Model output never becomes shell text."""

from __future__ import annotations

import io
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Protocol

from PIL import Image
from pydantic import ValidationError

from .models import Action, Point, ScreenSize
from .observation import TreeSnapshot, normalize_tree


class NativeError(RuntimeError):
    """Native failure with no raw app content or command input in its message."""


class NativeTransport(Protocol):
    commands: int
    failures: int
    mutations: int

    def tree(self) -> TreeSnapshot: ...
    def screenshot(self) -> bytes: ...
    def act(self, action: Action, snapshot: TreeSnapshot | None = None) -> None: ...


class AXeTransport:
    def __init__(
        self,
        udid: str,
        *,
        screen: ScreenSize,
        axe: str = "axe",
        command_timeout: float = 30,
        settle_seconds: float = 0.35,
    ) -> None:
        if not udid or udid == "booted":
            raise ValueError("Select one simulator by its explicit UDID")
        self.udid = udid
        self.screen = screen
        self.axe = axe
        self.command_timeout = command_timeout
        self.settle_seconds = settle_seconds
        self.commands = 0
        self.failures = 0
        self.mutations = 0

    def _command(self, arguments: list[str], *, stdin: bytes | None = None) -> bytes:
        self.commands += 1
        try:
            result = subprocess.run(
                arguments,
                input=stdin,
                capture_output=True,
                check=False,
                timeout=self.command_timeout,
            )
        except (OSError, subprocess.TimeoutExpired):
            self.failures += 1
            raise NativeError("Native command could not finish") from None
        if result.returncode != 0:
            self.failures += 1
            raise NativeError(f"Native command failed with exit code {result.returncode}")
        return result.stdout

    def _axe(self, *arguments: str, stdin: bytes | None = None) -> bytes:
        return self._command([self.axe, *arguments, "--udid", self.udid], stdin=stdin)

    def tree(self) -> TreeSnapshot:
        raw = self._axe("describe-ui")
        try:
            return normalize_tree(raw, screen=self.screen)
        except (ValidationError, ValueError):
            raise NativeError("AXe returned an unsupported accessibility tree") from None

    def screenshot(self) -> bytes:
        # A named file keeps binary screenshot data out of command output.
        with tempfile.TemporaryDirectory(prefix="axe-frame-") as directory:
            target = Path(directory) / "frame.png"
            self._command(["xcrun", "simctl", "io", self.udid, "screenshot", str(target)])
            try:
                data = target.read_bytes()
                with Image.open(io.BytesIO(data)) as image:
                    image.verify()
                return data
            except (OSError, ValueError):
                raise NativeError("Native screenshot is unavailable") from None

    def _tap(self, action: Action, snapshot: TreeSnapshot | None) -> None:
        point: Point | None
        if action.target_ref is not None:
            if snapshot is None:
                raise NativeError("Semantic tap needs its fresh observation")
            element = snapshot.resolve(action.target_ref)
            if not element.enabled:
                raise NativeError("Selected control is disabled")
            if (
                element.identifier
                and sum(
                    candidate.identifier == element.identifier for candidate in snapshot.elements
                )
                == 1
            ):
                self._axe("tap", "--id", element.identifier, "--element-type", element.role)
                return
            point = element.frame.center()
        else:
            point = action.point
        if point is None or point.x >= self.screen.width or point.y >= self.screen.height:
            raise NativeError("Tap point lies outside the supplied simulator geometry")
        self._axe("tap", "-x", str(point.x), "-y", str(point.y))

    def act(self, action: Action, snapshot: TreeSnapshot | None = None) -> None:
        if action.operation == "DONE":
            raise NativeError("Completion is an observation, not a native command")
        if action.operation == "TAP":
            self._tap(action, snapshot)
            self.mutations += 1
        elif action.operation == "TYPE_TEXT":
            if action.target_ref is not None:
                self._tap(Action(operation="TAP", target_ref=action.target_ref), snapshot)
                self.mutations += 1
            if action.replace:
                self._axe("key-combo", "--modifiers", "227", "--key", "4")
                self.mutations += 1
            self._axe("type", "--stdin", stdin=(action.text or "").encode())
            self.mutations += 1
        elif action.operation in {"SCROLL_UP", "SCROLL_DOWN"}:
            # AXe names finger direction. Reaching lower content needs an upward swipe.
            gesture = "scroll-down" if action.operation == "SCROLL_UP" else "scroll-up"
            self._axe(
                "gesture",
                gesture,
                "--screen-width",
                str(self.screen.width),
                "--screen-height",
                str(self.screen.height),
            )
            self.mutations += 1
        time.sleep(self.settle_seconds)
