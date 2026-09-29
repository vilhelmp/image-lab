import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import check_versions  # noqa: E402


def test_pins_match_readme_frontmatter() -> None:
    assert check_versions.check() == []
