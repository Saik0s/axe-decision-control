"""Installation contracts exercised against relocated, real source ZIP exports.

Fixtures use the public packager and synthetic selection sentinels; no providers,
models, native simulator commands, or installer side effects are involved.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import stat
from collections.abc import Iterator
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.parse import unquote, urlsplit
from zipfile import ZipFile

import pytest
from pydantic import BaseModel, ConfigDict

from tools.package_source import package

_REPO = Path(__file__).resolve().parents[1]
_SKILL_NAMES = {"axe-tree-control", "axe-grid-control"}
_MEDIA_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".mp4", ".mov"}
_LINK = re.compile(r"!?\[[^\]\n]*\]\(\s*(?:<(?P<angle>[^>\n]+)>|(?P<plain>[^\s)]+))")
_DEFINITION = re.compile(
    r"^\s{0,3}\[[^\]\n]+\]:\s*(?:<(?P<angle>[^>\n]+)>|(?P<plain>\S+))", re.MULTILINE
)


class PluginManifest(BaseModel):
    model_config = ConfigDict(strict=True)

    name: Literal["axe-decision-control"]
    version: Literal["0.2.0"]
    skills: Literal["./skills/"]


class LocalSource(BaseModel):
    model_config = ConfigDict(strict=True)

    source: Literal["local"]
    path: Literal["./"]


class MarketplacePlugin(BaseModel):
    model_config = ConfigDict(strict=True)

    name: Literal["axe-decision-control"]
    source: Literal["./"] | LocalSource


class Marketplace(BaseModel):
    model_config = ConfigDict(strict=True)

    plugins: list[MarketplacePlugin]


class ManualEvalCase(BaseModel):
    model_config = ConfigDict(strict=True)

    id: int
    prompt: str
    expectations: list[str]


class ManualEvalSuite(BaseModel):
    model_config = ConfigDict(strict=True)

    skill_name: Literal["axe-tree-control", "axe-grid-control"]
    evals: list[ManualEvalCase]


def _regular_files(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
        and not any(part in {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
                    for part in path.relative_to(root).parts)
        and path.suffix.lower() not in {".pyc", ".pyo"}
    }


def _export(root: Path, output: Path) -> set[str]:
    audit = package(root, output)
    assert audit["sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    with ZipFile(output) as archive:
        members = archive.namelist()
        assert members, "The source export is empty"
        assert len(members) == len(set(members)), "Duplicate ZIP members"
        assert audit["members"] == members, "Audit differs from the actual ZIP"
        for info in archive.infolist():
            path = PurePosixPath(info.filename)
            assert not path.is_absolute() and ".." not in path.parts, info.filename
            assert stat.S_ISREG(info.external_attr >> 16), info.filename
            assert not info.is_dir(), info.filename
            assert not info.filename.startswith(".agents/skills/"), info.filename
            assert not any(
                left == ".agents" and right == "runtime"
                for left, right in zip(path.parts, path.parts[1:], strict=False)
            ), info.filename
    return set(members)


@pytest.fixture(scope="module")
def relocated_export(tmp_path_factory: pytest.TempPathFactory) -> Path:
    build = tmp_path_factory.mktemp("source-export").resolve()
    archive_path = build / "source.zip"
    _export(_REPO, archive_path)
    destination = tmp_path_factory.mktemp("unrelated-install-location").resolve()
    moved_archive = destination / "copied-source.zip"
    shutil.copyfile(archive_path, moved_archive)
    installed = destination / "plugin"
    with ZipFile(moved_archive) as archive:
        archive.extractall(installed)
    assert installed.is_dir() and not installed.is_relative_to(_REPO)
    assert all(not path.is_symlink() for path in installed.rglob("*"))
    return installed


@pytest.mark.parametrize(
    "marketplace_path,manifest_path,local_source",
    [
        (".claude-plugin/marketplace.json", ".claude-plugin/plugin.json", False),
        (".agents/plugins/marketplace.json", ".codex-plugin/plugin.json", True),
    ],
)
def test_marketplace_discovers_both_canonical_skills_in_relocated_zip(
    relocated_export: Path, marketplace_path: str, manifest_path: str, local_source: bool,
) -> None:
    marketplace = Marketplace.model_validate_json(
        (relocated_export / marketplace_path).read_text(encoding="utf-8")
    )
    assert len(marketplace.plugins) == 1
    entry = marketplace.plugins[0]
    if local_source:
        assert isinstance(entry.source, LocalSource)
        source_path = entry.source.path
    else:
        assert isinstance(entry.source, str)
        source_path = entry.source
    # Marketplace sources are resolved from the repository, not metadata directory.
    plugin_root = (relocated_export / source_path).resolve()
    assert plugin_root == relocated_export
    manifest = PluginManifest.model_validate_json(
        (plugin_root / manifest_path).read_text(encoding="utf-8")
    )
    skill_root = (plugin_root / manifest.skills).resolve()
    assert skill_root.is_relative_to(plugin_root)
    assert {path.name for path in skill_root.iterdir() if path.is_dir()} == _SKILL_NAMES
    assert set(skill_root.rglob("SKILL.md")) == {
        skill_root / name / "SKILL.md" for name in _SKILL_NAMES
    }
    for name in _SKILL_NAMES:
        skill = skill_root / name
        assert (skill / "SKILL.md").is_file()
        assert (skill / "agents/openai.yaml").read_text(encoding="utf-8").strip()
        assert list((skill / "references").glob("*.md")), name


def _markdown_targets(text: str) -> Iterator[str]:
    for pattern in (_LINK, _DEFINITION):
        for match in pattern.finditer(text):
            yield match.group("angle") or match.group("plain")


def _assert_skill_portable(skill: Path) -> None:
    markdown = sorted(skill.rglob("*.md"))
    assert markdown, skill
    local_references = 0
    for document in markdown:
        text = document.read_text(encoding="utf-8")
        assert "../../../docs" not in text, document
        assert not re.search(r"\brtk\b", text), document
        assert not re.search(r"\buv\s+(?:--\S+\s+)*run\b", text), document
        assert not re.search(
            r"\bpython(?:3)?\s+(?:-m\s+)?(?:tools|benchmarks|src)(?:[./]|\b)", text
        ), document
        for target in _markdown_targets(text):
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            relative = Path(unquote(parsed.path))
            assert not relative.is_absolute(), f"Absolute skill reference: {document}: {target}"
            resolved = (document.parent / relative).resolve()
            assert resolved.is_relative_to(skill), f"Escaping skill reference: {document}: {target}"
            assert resolved.exists(), f"Missing skill reference: {document}: {target}"
            assert not resolved.is_symlink(), f"Symlink skill reference: {document}: {target}"
            local_references += 1
    assert local_references, f"No bundled references linked from {skill}"


def _assert_manual_evals(skill: Path) -> None:
    suite = ManualEvalSuite.model_validate_json(
        (skill / "evals/evals.json").read_text(encoding="utf-8")
    )
    assert suite.skill_name == skill.name
    assert suite.evals, f"No manual routing/safety cases for {skill}"
    identifiers = [case.id for case in suite.evals]
    assert len(identifiers) == len(set(identifiers)), f"Duplicate case IDs in {skill}"
    for case in suite.evals:
        assert case.prompt.strip(), f"Empty prompt in {skill}, case {case.id}"
        assert case.expectations, f"No expectations in {skill}, case {case.id}"
        assert all(expectation.strip() for expectation in case.expectations), case.id


@pytest.mark.parametrize("skill_name", sorted(_SKILL_NAMES))
def test_skill_links_resolve_and_commands_are_portable_after_individual_copy(
    relocated_export: Path, tmp_path: Path, skill_name: str,
) -> None:
    bundled = relocated_export / "skills" / skill_name
    _assert_skill_portable(bundled)
    _assert_manual_evals(bundled)
    standalone = tmp_path.resolve() / "individual-install" / skill_name
    shutil.copytree(bundled, standalone)
    assert {path.name for path in standalone.parent.iterdir()} == {skill_name}
    _assert_skill_portable(standalone)
    _assert_manual_evals(standalone)


@pytest.mark.parametrize("skill_name", sorted(_SKILL_NAMES))
def test_missing_reference_in_individual_skill_copy_is_rejected(
    relocated_export: Path, tmp_path: Path, skill_name: str,
) -> None:
    standalone = tmp_path.resolve() / skill_name
    shutil.copytree(relocated_export / "skills" / skill_name, standalone)
    _assert_skill_portable(standalone)
    targets = _markdown_targets((standalone / "SKILL.md").read_text(encoding="utf-8"))
    target = next(path for path in targets if path.startswith("references/"))
    reference = standalone / target
    reference.rename(tmp_path.resolve() / reference.name)
    with pytest.raises(AssertionError, match="Missing skill reference:"):
        _assert_skill_portable(standalone)


def test_educational_docs_and_recorded_media_survive_export(relocated_export: Path) -> None:
    assert (relocated_export / "CLAUDE.md").read_text(encoding="utf-8").strip()
    for directory in ("docs", "results"):
        source = _REPO / directory
        expected_docs = {path for path in _regular_files(source) if path.endswith(".md")}
        expected_media = {
            path for path in _regular_files(source) if Path(path).suffix.lower() in _MEDIA_SUFFIXES
        }
        assert expected_docs, f"No educational Markdown in {directory}"
        if directory == "results":
            assert expected_media, "No recorded results media"
        exported = _regular_files(relocated_export / directory)
        assert expected_docs <= exported, expected_docs - exported
        assert expected_media <= exported, expected_media - exported
    for relative in ("docs/index.html", "docs/learning.js"):
        source_asset = _REPO / relative
        if source_asset.is_file():
            assert (relocated_export / relative).read_bytes() == source_asset.read_bytes(), relative
    for directory in ("evals", ".github"):
        expected = _regular_files(_REPO / directory)
        assert expected, f"Required source root is empty: {directory}"
        exported = _regular_files(relocated_export / directory)
        assert expected <= exported, expected - exported
        for relative in expected:
            assert (relocated_export / directory / relative).read_bytes() == (
                _REPO / directory / relative
            ).read_bytes(), relative


def _write(root: Path, relative: str, content: bytes = b"synthetic packaging sentinel\n") -> None:
    destination = root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)


def test_selection_excludes_runtime_legacy_skills_and_symlinks_without_duplicates(
    relocated_export: Path, tmp_path: Path,
) -> None:
    source = tmp_path.resolve() / "controlled-checkout"
    shutil.copytree(relocated_export, source)
    included = {
        "docs/packaging-example.md",
        "docs/media/packaging-example.svg",
        "results/packaging-example/recording.mp4",
        "skills/axe-tree-control/references/packaging-example.md",
        "evals/packaging-example.json",
        ".github/workflows/packaging-example.yml",
    }
    excluded = {
        ".agents/runtime/ignored-sentinel.json",
        ".agents/skills/axe-tree-control/SKILL.md",
        ".agents/skills/axe-grid-control/SKILL.md",
        "workspace-only/ignored-sentinel.md",
        "docs/.agents/runtime/ignored-sentinel.json",
        "docs/__pycache__/ignored-sentinel.pyc",
        "docs/ignored-sentinel.pyc",
        "docs/linked-file.md",
        "docs/linked-directory/ignored-sentinel.md",
        "evals/__pycache__/ignored-sentinel.pyc",
        "evals/ignored-sentinel.pyc",
        "artifacts/evaluations/ignored-sentinel.json",
        "media/ignored-sentinel.svg",
    }
    for relative in included | (excluded - {
        "docs/linked-file.md", "docs/linked-directory/ignored-sentinel.md",
    }):
        _write(source, relative)
    outside = tmp_path.resolve() / "outside-checkout"
    _write(outside, "ignored-sentinel.md")
    (source / "docs/linked-file.md").symlink_to(outside / "ignored-sentinel.md")
    (source / "docs/linked-directory").symlink_to(outside, target_is_directory=True)
    members = _export(source, tmp_path.resolve() / "controlled-source.zip")
    assert included <= members, included - members
    assert excluded.isdisjoint(members), excluded & members
    with ZipFile(tmp_path.resolve() / "controlled-source.zip") as archive:
        for relative in included:
            assert archive.read(relative) == (source / relative).read_bytes(), relative


@pytest.mark.parametrize("required_root", ["evals", ".github"])
def test_missing_evaluators_or_ci_refuses_incomplete_source_zip(
    relocated_export: Path, tmp_path: Path, required_root: str,
) -> None:
    source = tmp_path.resolve() / "incomplete-checkout"
    shutil.copytree(relocated_export, source)
    (source / required_root).rename(tmp_path.resolve() / "omitted-root")
    output = tmp_path.resolve() / "incomplete-source.zip"
    with pytest.raises(ValueError, match=f"Missing selected root: {re.escape(required_root)}"):
        package(source, output)
    assert not output.exists(), "Refused export left a misleading source ZIP"
