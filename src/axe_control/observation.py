"""Normalize AXe's external tree into snapshot-local, visible candidates."""

from __future__ import annotations

import hashlib

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

from .models import Frame, ScreenSize

JSON: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)
INTERACTIVE = {
    "Button",
    "Cell",
    "CheckBox",
    "Link",
    "MenuItem",
    "PopUpButton",
    "RadioButton",
    "SecureTextField",
    "SegmentedControl",
    "Switch",
    "Tab",
    "TabBarButton",
    "TextField",
    "Toggle",
}


class AXNode(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    label: str | None = Field(default=None, validation_alias=AliasChoices("AXLabel", "label"))
    identifier: str | None = Field(
        default=None, validation_alias=AliasChoices("AXUniqueId", "AXIdentifier", "identifier")
    )
    value: str | int | float | bool | None = Field(
        default=None, validation_alias=AliasChoices("AXValue", "value")
    )
    role: str = Field(default="", validation_alias=AliasChoices("type", "role"))
    enabled: bool = Field(
        default=True, validation_alias=AliasChoices("enabled", "isEnabled", "AXEnabled")
    )
    frame: Frame | None = None
    children: list[AXNode] = Field(default_factory=list)


class Element(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    ref: str
    label: str = Field(repr=False)
    role: str
    value: str | int | float | bool | None = Field(default=None, repr=False)
    enabled: bool
    frame: Frame
    identifier: str | None = Field(default=None, repr=False)

    def state(self) -> JsonValue:
        return JSON.validate_json(self.model_dump_json(exclude={"identifier", "frame"}))


class TreeSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    text: list[str] = Field(repr=False)
    elements: list[Element] = Field(repr=False)
    digest: str
    truncated: bool

    def state(self) -> JsonValue:
        return {
            "screen_text": list(self.text),
            "candidates": [element.state() for element in self.elements],
            "candidates_truncated": self.truncated,
        }

    def resolve(self, ref: str) -> Element:
        for element in self.elements:
            if element.ref == ref:
                return element
        raise ValueError("The target reference does not belong to this observation")


TREE: TypeAdapter[AXNode | list[AXNode]] = TypeAdapter(AXNode | list[AXNode])


def normalize_tree(
    raw: bytes | str, *, screen: ScreenSize | None = None, max_candidates: int = 25
) -> TreeSnapshot:
    root = TREE.validate_json(raw)
    roots = root if isinstance(root, list) else [root]
    text: list[str] = []
    candidates: list[Element] = []
    semantic: list[JsonValue] = []

    def walk(node: AXNode, in_keyboard: bool = False) -> None:
        role = node.role.removeprefix("AX")
        keyboard = in_keyboard or role == "Keyboard"
        label = node.label or ""
        frame = node.frame
        visible = frame is not None and frame.width > 0 and frame.height > 0
        if frame is not None:
            visible = visible and frame.x + frame.width > 0 and frame.y + frame.height > 0
            if screen is not None:
                visible = visible and frame.x < screen.width and frame.y < screen.height
        if visible:
            semantic.append(JSON.validate_json(node.model_dump_json(exclude={"children"})))
            if label and not keyboard and label not in text:
                text.append(label)
            useful_key = not keyboard or label.lower() in {"done", "return", "next", "search"}
            if (
                frame is not None
                and role in INTERACTIVE
                and useful_key
                and (label or node.identifier)
            ):
                candidates.append(
                    Element(
                        ref=f"e{len(candidates) + 1}",
                        label=label,
                        role=role,
                        value=node.value,
                        enabled=node.enabled,
                        frame=frame,
                        identifier=node.identifier,
                    )
                )
        for child in node.children:
            walk(child, keyboard)

    for node in roots:
        walk(node)
    digest = hashlib.sha256(JSON.dump_json(semantic)).hexdigest()
    return TreeSnapshot(
        text=text,
        elements=candidates[:max_candidates],
        digest=digest,
        truncated=len(candidates) > max_candidates,
    )
