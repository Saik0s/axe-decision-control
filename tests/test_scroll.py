import subprocess

import pytest

from axe_control.models import Action, ScreenSize
from axe_control.native import AXeTransport


def test_lower_content_uses_upward_finger_gesture_and_supplied_geometry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    def command(arguments: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        commands.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", command)
    native = AXeTransport(
        "explicit-test-udid",
        screen=ScreenSize(width=420.0, height=900.0),
        settle_seconds=0,
    )
    native.act(Action(operation="SCROLL_DOWN"))
    assert commands == [
        [
            "axe",
            "gesture",
            "scroll-up",
            "--screen-width",
            "420.0",
            "--screen-height",
            "900.0",
            "--udid",
            "explicit-test-udid",
        ]
    ]
