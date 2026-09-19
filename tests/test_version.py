"""One version everywhere (F14)."""

import re
from pathlib import Path

from core.config import PROTOCOL_VERSION
from core.version import __version__

ROOT = Path(__file__).resolve().parent.parent


def test_protocol_version_is_the_package_version():
    assert PROTOCOL_VERSION == __version__


def test_pyproject_reads_the_version_constant():
    text = (ROOT / "pyproject.toml").read_text()
    assert 'dynamic = ["version"]' in text
    assert 'version = {attr = "core.version.__version__"}' in text
    assert not re.search(r'^version\s*=\s*"', text, re.MULTILINE)


def test_changelog_head_is_the_package_version():
    text = (ROOT / "CHANGELOG.md").read_text()
    head = re.search(r"^## \[([^\]]+)\]", text, re.MULTILINE).group(1)
    assert head == __version__


def test_new_pid_records_the_package_version():
    from crypto.pid import generate_pid
    assert generate_pid()["protocol"] == __version__
