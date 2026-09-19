"""
REFInet Pillar — the single version constant.

Every place that reports a version (pyproject, PROTOCOL_VERSION, new
pid.json files, /identity/v3.json) reads this value. tests/test_version.py
asserts pyproject.toml and CHANGELOG.md agree with it.
"""

__version__ = "0.5.0"
