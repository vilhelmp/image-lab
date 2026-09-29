"""Dry-run the Space's pip install so pin conflicts fail in CI, not on the Space."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import check_versions

ROOT = Path(__file__).resolve().parent.parent

# Mirrors the Space build log. Update these if the Space's install line changes.
SPACE_EXTRAS = ["torch<=2.13.0", "uvicorn>=0.14.0", "websockets>=10.4", "spaces==0.51.3"]


def main() -> int:
    python_version = (ROOT / ".python-version").read_text(encoding="utf-8").strip()
    lines = [f"gradio[oauth,mcp]=={check_versions.gradio_pin()}", *SPACE_EXTRAS]
    with tempfile.TemporaryDirectory() as tmp:
        extras = Path(tmp) / "space_extras.txt"
        extras.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = subprocess.run(
            [
                "uv",
                "pip",
                "compile",
                str(ROOT / "requirements.txt"),
                str(extras),
                "--python-version",
                python_version,
                "--no-header",
                "-q",
                "-o",
                str(Path(tmp) / "resolved.txt"),
            ],
            check=False,
        )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
