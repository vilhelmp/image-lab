"""Fail if pinned versions drift from the Hugging Face README frontmatter (spec 18.2)."""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def gradio_pin() -> str:
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "dependencies"
    ]
    for dep in deps:
        match = re.fullmatch(r"gradio(?:\[[^\]]*\])?==([^\s;]+)", dep.strip())
        if match:
            return match.group(1)
    raise SystemExit("pyproject.toml must pin gradio with '==X.Y.Z'.")


def readme_frontmatter() -> dict[str, str]:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    match = re.match(r"---\r?\n(.*?)\r?\n---", text, re.DOTALL)
    if not match:
        raise SystemExit("README.md is missing YAML frontmatter.")
    return yaml.safe_load(match.group(1))


def check() -> list[str]:
    front = readme_frontmatter()
    python_version = (ROOT / ".python-version").read_text(encoding="utf-8").strip()
    errors = []
    if str(front.get("sdk_version")) != gradio_pin():
        errors.append(f"sdk_version {front.get('sdk_version')!r} != gradio pin {gradio_pin()!r}")
    if str(front.get("python_version")) != python_version:
        errors.append(
            f"python_version {front.get('python_version')!r} != .python-version {python_version!r}"
        )
    return errors


if __name__ == "__main__":
    problems = check()
    for problem in problems:
        print(f"ERROR: {problem}", file=sys.stderr)
    sys.exit(1 if problems else 0)
