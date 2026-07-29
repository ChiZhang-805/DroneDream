#!/usr/bin/env python3
"""Fast, dependency-free repository hygiene checks.

This check deliberately inspects project-owned inputs rather than generated
build output.  It is suitable for both local worktrees and a clean CI checkout.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
IGNORED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "coverage",
    "dist",
    "htmlcov",
    "node_modules",
    "site-dist",
    "target",
}
TEXT_SUFFIXES = {
    ".cjs",
    ".conf",
    ".css",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".mjs",
    ".nsh",
    ".ps1",
    ".py",
    ".rs",
    ".service",
    ".sh",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}
TEXT_NAMES = {
    ".dockerignore",
    ".env.example",
    ".gitattributes",
    ".gitignore",
    "Dockerfile",
    "LICENSE",
}
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
SECRET_PATTERNS = {
    "PEM private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "Alibaba Cloud AccessKey": re.compile(r"\bLTAI[A-Za-z0-9]{12,}\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"),
    "OpenAI API key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
}
SAFE_SECRET_TEST_SENTINELS = {
    "OpenAI API key": frozenset({"sk-contract-persistence-test"}),
}


def probable_secret_names(text: str) -> list[str]:
    """Return secret classes with at least one non-sentinel match."""

    result: list[str] = []
    for secret_name, pattern in SECRET_PATTERNS.items():
        sentinels = SAFE_SECRET_TEST_SENTINELS.get(secret_name, frozenset())
        if any(match.group(0) not in sentinels for match in pattern.finditer(text)):
            result.append(secret_name)
    return result


def project_files() -> list[Path]:
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git is required to enumerate repository-owned files")
    result = subprocess.run(  # noqa: S603 - absolute trusted git executable, fixed arguments.
        [git, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    paths = [Path(raw.decode("utf-8")) for raw in result.stdout.split(b"\0") if raw]
    return [
        path
        for path in paths
        if not any(part in IGNORED_PARTS for part in path.parts) and (ROOT / path).is_file()
    ]


def is_text(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES or path.name in TEXT_NAMES


def markdown_target(raw_target: str) -> str | None:
    target = raw_target.strip()
    if target.startswith("<") and ">" in target:
        target = target[1 : target.index(">")]
    elif " " in target:
        # Markdown permits an optional quoted title after the destination.
        possible_target, possible_title = target.split(" ", 1)
        if possible_title.lstrip().startswith(('"', "'", "(")):
            target = possible_target
    target = unquote(target.split("#", 1)[0]).strip()
    if not target or re.match(r"^(?:[a-z][a-z0-9+.-]*:|#)", target, re.I):
        return None
    return target


def main() -> int:
    errors: list[str] = []
    files = project_files()
    text_files = 0
    json_files = 0
    toml_files = 0
    markdown_files = 0
    relative_links = 0

    casefolded_paths: dict[str, Path] = {}
    for relative_path in files:
        folded = relative_path.as_posix().casefold()
        previous = casefolded_paths.get(folded)
        if previous is not None and previous != relative_path:
            errors.append(f"case-insensitive path collision: {previous} and {relative_path}")
        casefolded_paths[folded] = relative_path

    for relative_path in files:
        absolute_path = ROOT / relative_path
        if not is_text(relative_path):
            continue
        text_files += 1
        try:
            text = absolute_path.read_text(encoding="utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            errors.append(f"{relative_path}: invalid UTF-8 ({exc})")
            continue
        if "\ufffd" in text:
            errors.append(f"{relative_path}: contains a Unicode replacement character")
        if "\x00" in text:
            errors.append(f"{relative_path}: contains a NUL byte")
        for secret_name in probable_secret_names(text):
            errors.append(f"{relative_path}: contains a probable {secret_name}")

        if relative_path.suffix.lower() == ".json":
            json_files += 1
            try:
                json.loads(text)
            except json.JSONDecodeError as exc:
                errors.append(f"{relative_path}:{exc.lineno}:{exc.colno}: invalid JSON ({exc.msg})")

        if relative_path.suffix.lower() == ".toml":
            toml_files += 1
            try:
                tomllib.loads(text)
            except tomllib.TOMLDecodeError as exc:
                errors.append(f"{relative_path}: invalid TOML ({exc})")

        if relative_path.suffix.lower() != ".md":
            continue
        markdown_files += 1
        fence_count = sum(1 for line in text.splitlines() if re.match(r"^\s*```", line))
        if fence_count % 2:
            errors.append(f"{relative_path}: unbalanced fenced code blocks")
        for line_number, line in enumerate(text.splitlines(), start=1):
            for match in MARKDOWN_LINK.finditer(line):
                target = markdown_target(match.group(1))
                if target is None:
                    continue
                relative_links += 1
                candidate = (absolute_path.parent / target).resolve()
                try:
                    candidate.relative_to(ROOT)
                except ValueError:
                    errors.append(
                        f"{relative_path}:{line_number}: local link escapes "
                        f"the repository: {target}"
                    )
                    continue
                if not candidate.exists():
                    errors.append(
                        f"{relative_path}:{line_number}: missing local link target: {target}"
                    )

    print(
        "Repository hygiene: "
        f"{len(files)} files, {text_files} text files, {json_files} JSON files, "
        f"{toml_files} TOML files, "
        f"{markdown_files} Markdown files, {relative_links} local links"
    )
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print(f"Repository hygiene failed with {len(errors)} error(s).", file=sys.stderr)
        return 1
    print("Repository hygiene passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
