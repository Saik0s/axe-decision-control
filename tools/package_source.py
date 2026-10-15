"""Package selected checkout files without building a wheel or calling services.

Run with uv run --no-sync --offline python -B tools/package_source.py --output ZIP.
The output parent must exist. A failed write retains any partial output, which
must not be reused. Benchmark results and docs must be finalized by the caller
before treating an archive as a release. Prints SHA-256 and members.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import stat
from collections.abc import Iterator
from pathlib import Path
from typing import TypedDict
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

SELECTED_ROOTS: tuple[str, ...] = (
    ".gitignore", "AGENTS.md", "CLAUDE.md", "LICENSE", "README.md", "pyproject.toml", "uv.lock",
    "src", "benchmarks", "docs", "tests", "tools", "fixtures", "evals", ".github",
    ".claude-plugin", ".codex-plugin", ".agents/plugins", "skills", "results",
)
EXCLUDED_NAMES: frozenset[str] = frozenset({
    ".git", ".venv", "venv", "__pycache__", "cache", "caches", ".cache",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".hypothesis", ".tox", ".nox",
    "benchmark-runs", "dist", "build", "artifacts", "models", "weights", ".ds_store",
    "private", ".private", "credentials", "secrets",
})
EXCLUDED_SUFFIXES: frozenset[str] = frozenset({
    ".pyc", ".pyo", ".pyd", ".o", ".a", ".so", ".dylib", ".dll", ".exe", ".whl",
    ".app", ".bundle", ".framework", ".xcarchive", ".dsym", ".egg-info", ".dist-info",
    ".gguf", ".ggml", ".safetensors", ".pt", ".pth", ".bin", ".ckpt", ".onnx",
    ".pb", ".h5", ".hdf5", ".npz", ".npy", ".tflite", ".mlmodel", ".mlmodelc",
    ".mlpackage", ".weights", ".ot", ".msgpack", ".pem", ".key",
})
FIXTURE_SUFFIXES: frozenset[str] = frozenset({
    ".swift", ".py", ".md", ".txt", ".json", ".toml", ".yaml", ".yml", ".plist",
    ".h", ".m", ".mm", ".c", ".cpp", ".sh",
})
PRIVATE_CONFIG_SUFFIXES: frozenset[str] = frozenset({
    ".json", ".yaml", ".yml", ".toml", ".plist", ".env", ".log", ".txt", ".sh",
})


class Audit(TypedDict):
    sha256: str
    members: list[str]


def has_symlink(path: Path) -> bool:
    return any(parent.is_symlink() for parent in (path, *path.parents))


def excluded(relative: Path) -> bool:
    parts = tuple(part.casefold() for part in relative.parts)
    if any(part in EXCLUDED_NAMES or part.startswith(".env")
           or part.endswith("_cache") for part in parts):
        return True
    if any(left == ".agents" and right == "runtime"
           for left, right in zip(parts, parts[1:], strict=False)):
        return True
    for part in parts:
        path = Path(part)
        tokens = set(path.stem.replace("_", "-").split("-"))
        if path.suffix in PRIVATE_CONFIG_SUFFIXES and tokens & {
            "launch", "private", "credentials", "secrets"
        }:
            return True
    return any(suffix.casefold() in EXCLUDED_SUFFIXES
               for part in relative.parts for suffix in Path(part).suffixes)


def walk(root: Path, path: Path) -> Iterator[Path]:
    relative = path.relative_to(root)
    if excluded(relative) or path.is_symlink():
        return
    mode = path.stat(follow_symlinks=False).st_mode
    if stat.S_ISDIR(mode):
        for child in sorted(path.iterdir()):
            yield from walk(root, child)
    elif stat.S_ISREG(mode):
        if relative.parts[0] != "fixtures" or path.suffix.casefold() in FIXTURE_SUFFIXES:
            yield path


def inventory(root: Path) -> list[Path]:
    files: list[Path] = []
    for name in SELECTED_ROOTS:
        selected = root / name
        if has_symlink(selected):
            continue
        if not selected.exists():
            raise ValueError(f"Missing selected root: {name}")
        files.extend(walk(root, selected))
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


def validate_output(root: Path, output: Path) -> Path:
    candidate = output.expanduser().absolute()
    if has_symlink(candidate):
        raise ValueError("Output and its parents must not be symlinks")
    candidate = candidate.resolve()
    if any(candidate.is_relative_to(root / name) for name in SELECTED_ROOTS):
        raise ValueError("Output must be outside the selected roots")
    if candidate.exists():
        raise ValueError("Output already exists; choose a new path")
    if not candidate.parent.is_dir():
        raise ValueError("Output parent directory must already exist")
    return candidate


def read_regular(path: Path) -> bytes:
    if has_symlink(path):
        raise ValueError("A selected file became a symlink")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("Selected input must be a regular file")
        data = source.read()
        after = os.fstat(source.fileno())
    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
        after.st_size, after.st_mtime_ns, after.st_ctime_ns
    ):
        raise ValueError("Selected input changed while being read; retry after it is stable")
    return data


def package(root: Path, output: Path) -> Audit:
    root = root.resolve()
    destination = validate_output(root, output)
    members: list[str] = []
    # Build before reserving the output so a source failure leaves no partial ZIP.
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for path in inventory(root):
            name = path.relative_to(root).as_posix()
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, read_regular(path), compress_type=ZIP_DEFLATED, compresslevel=9)
            members.append(name)
    payload = buffer.getvalue()
    validate_output(root, destination)
    try:
        with destination.open("xb") as output_file:
            if output_file.write(payload) != len(payload):
                raise OSError("Incomplete output write")
    except FileExistsError:
        raise
    except OSError as error:
        raise OSError(
            "Output write failed; any partial output is retained, choose a new path"
        ) from error
    return {"sha256": hashlib.sha256(payload).hexdigest(), "members": members}


class Arguments(argparse.Namespace):
    output: Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, metavar="ZIP")
    arguments = parser.parse_args(namespace=Arguments())
    try:
        audit = package(Path(__file__).resolve().parents[1], arguments.output)
    except (OSError, ValueError) as error:
        parser.exit(2, f"Source package refused: {error}\n")
    print(json.dumps(audit, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
