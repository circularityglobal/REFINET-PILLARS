from __future__ import annotations

"""
REFInet Pillar — DApp Definition Format Parser

DApps are plain text .dapp files served from gopherroot/dapps/.
Each file declares a decentralized application with metadata, ABI,
documentation, interaction flows, and warnings.

Hot-reload is implemented by rescanning the dapps directory on every
``/dapps`` request (see ``load_all_dapps()``).  This is intentional for
v0.1 — it keeps the code simple and ensures new or updated .dapp files
are picked up immediately without a Pillar restart.
"""

import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List

from core.config import GOPHER_ROOT


@dataclass
class DAppDefinition:
    name: str
    slug: str
    version: str
    chain_id: int
    contract: str
    author_pid: str
    author_address: str
    description: str
    published: str
    abi_functions: List[str] = field(default_factory=list)
    docs: Dict[str, str] = field(default_factory=dict)
    flows: Dict[str, List[str]] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)


def parse_dapp_file(filepath: str | Path) -> DAppDefinition:
    """Parse a .dapp definition file into a DAppDefinition."""
    text = Path(filepath).read_text(encoding="utf-8")
    sections = _split_sections(text)

    meta = _parse_meta(sections.get("meta", ""))
    abi = _parse_abi(sections.get("abi", ""))
    docs = _parse_docs(sections.get("docs", ""))
    flows = _parse_flows(sections.get("flows", ""))
    warnings = _parse_warnings(sections.get("warnings", ""))

    return DAppDefinition(
        name=meta.get("name", ""),
        slug=meta.get("slug", ""),
        version=meta.get("version", "1.0.0"),
        chain_id=int(meta.get("chain_id", 1)),
        contract=meta.get("contract", ""),
        author_pid=meta.get("author_pid", ""),
        author_address=meta.get("author_address", ""),
        description=meta.get("description", ""),
        published=meta.get("published", ""),
        abi_functions=abi,
        docs=docs,
        flows=flows,
        warnings=warnings,
    )


def list_dapp_files() -> list[Path]:
    """List all .dapp files in gopherroot/dapps/."""
    dapps_dir = GOPHER_ROOT / "dapps"
    if not dapps_dir.exists():
        return []
    return sorted(dapps_dir.glob("*.dapp"))


def load_all_dapps() -> list[DAppDefinition]:
    """Load and parse all .dapp files."""
    dapps = []
    for path in list_dapp_files():
        try:
            dapps.append(parse_dapp_file(path))
        except Exception:
            continue
    return dapps


def get_dapp_count() -> int:
    """Return the number of .dapp files available."""
    return len(list_dapp_files())


def _split_sections(text: str) -> dict:
    """Split [section] blocks into a dict. Preserves all content within sections."""
    sections = {}
    current = None
    lines = []
    for line in text.splitlines():
        m = re.match(r"^\[(\w+)\]$", line.strip())
        if m:
            if current:
                sections[current] = "\n".join(lines)
            current = m.group(1)
            lines = []
        elif current:
            lines.append(line)
        # Lines before any section (top-level comments) are ignored
    if current:
        sections[current] = "\n".join(lines)
    return sections


def _parse_meta(text: str) -> dict:
    meta = {}
    for line in text.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            meta[k.strip()] = v.strip()
    return meta


def _parse_abi(text: str) -> list[str]:
    return [
        line.strip() for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _parse_docs(text: str) -> dict:
    docs = {}
    current_fn = None
    lines = []
    for line in text.splitlines():
        if line.startswith("# "):
            if current_fn:
                docs[current_fn] = "\n".join(lines).strip()
            current_fn = line[2:].strip()
            lines = []
        else:
            lines.append(line)
    if current_fn:
        docs[current_fn] = "\n".join(lines).strip()
    return docs


def _parse_flows(text: str) -> dict:
    flows = {}
    current = None
    steps = []
    for line in text.splitlines():
        if line.rstrip().endswith(":") and not line.startswith(" "):
            if current:
                flows[current] = steps
            current = line.rstrip(":").strip()
            steps = []
        elif line.strip() and re.match(r"^\d+\.\s", line.strip()):
            steps.append(re.sub(r"^\d+\.\s*", "", line.strip()))
    if current:
        flows[current] = steps
    return flows


def _parse_warnings(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]
