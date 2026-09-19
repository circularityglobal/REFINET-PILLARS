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


# ---------------------------------------------------------------------------
# The website ships copies of the root documents. They drifted once already:
# the 0.5.0 changelog entry and two whitepaper sections never reached the
# website copy, so refinet.io described a different product.
# ---------------------------------------------------------------------------
MIRRORED_DOCS = [
    "CHANGELOG.md", "WHITEPAPER.md", "SECURITY.md",
    "PLATFORM_OVERVIEW.md", "GETTING-STARTED.md", "DEV_GUIDE.md",
]


def test_website_doc_copies_match_the_originals():
    drifted = []
    for name in MIRRORED_DOCS:
        mirror = ROOT / "website" / "docs" / name
        if not mirror.exists():
            continue
        if mirror.read_text(encoding="utf-8") != (ROOT / name).read_text(encoding="utf-8"):
            drifted.append(name)
    assert drifted == [], (
        f"website/docs copies differ from the originals: {drifted}. "
        f"Copy the root document over its website/docs counterpart."
    )


def test_every_source_module_is_in_the_platform_overview_index():
    """New modules kept being added without ever appearing in the index."""
    overview = (ROOT / "PLATFORM_OVERVIEW.md").read_text(encoding="utf-8")
    packages = ["auth", "cli", "core", "crypto", "db", "integration",
                "mesh", "onboarding", "proxy", "rpc", "vault"]
    missing = []
    for pkg in packages:
        for path in sorted((ROOT / pkg).glob("*.py")):
            if path.name == "__init__.py":
                continue
            if f"{pkg}/{path.name}" not in overview:
                missing.append(f"{pkg}/{path.name}")
    assert missing == [], f"modules missing from PLATFORM_OVERVIEW.md: {missing}"


def test_documented_test_counts_are_not_overstated():
    """Docs may lag behind reality, but must never claim more than exists."""
    import re
    import subprocess
    import sys

    actual_modules = len(list((ROOT / "tests").glob("test_*.py")))
    for name in ("PLATFORM_OVERVIEW.md", "DEV_GUIDE.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        for claimed in re.findall(r"across \*{0,2}(\d+) modules", text):
            assert int(claimed) <= actual_modules, (
                f"{name} claims {claimed} test modules; {actual_modules} exist")
