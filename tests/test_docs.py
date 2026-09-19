"""The README's project tree must describe the repository that exists (F19)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _readme_tree_entries() -> list[str]:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    block = text.split("## Project Structure", 1)[1].split("```", 2)[1]
    entries = []
    for line in block.splitlines():
        m = re.match(r"^[│├└─\s]+([\w.\-]+/?)\s", line + " ")
        if m:
            entries.append(m.group(1))
    return entries


def test_readme_tree_is_not_empty():
    assert len(_readme_tree_entries()) > 10


def test_every_readme_tree_entry_exists():
    missing = [e for e in _readme_tree_entries() if not (ROOT / e.rstrip("/")).exists()]
    assert missing == [], f"README.md lists paths that do not exist: {missing}"


def test_every_top_level_package_is_in_readme_tree():
    listed = {e.rstrip("/") for e in _readme_tree_entries()}
    packages = {
        p.name for p in ROOT.iterdir()
        if p.is_dir() and (p / "__init__.py").exists() and p.name != "tests"
    }
    assert packages - listed == set(), f"Packages missing from README tree: {packages - listed}"
