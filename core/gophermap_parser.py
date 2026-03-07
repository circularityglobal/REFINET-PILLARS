"""
REFInet Pillar — Gophermap Parser (RFC 1436)

Parses Gopher menu responses into structured items.
Used by the replication system and any local browsing features.
"""

from dataclasses import dataclass, field
from typing import List

GOPHER_TYPES = {
    "0": "text",
    "1": "menu",
    "2": "cso",
    "3": "error",
    "4": "binhex",
    "5": "dos_binary",
    "6": "uuencode",
    "7": "search",
    "8": "telnet",
    "9": "binary",
    "+": "mirror",
    "g": "gif",
    "I": "image",
    "T": "tn3270",
    "h": "html",
    "i": "info",
    "s": "sound",
}


@dataclass
class GophermapItem:
    item_type: str
    display: str
    selector: str
    host: str
    port: int
    type_name: str = ""
    is_info: bool = False

    def __post_init__(self):
        self.type_name = GOPHER_TYPES.get(self.item_type, "unknown")
        self.is_info = self.item_type == "i"


@dataclass
class ParsedGophermap:
    items: List[GophermapItem] = field(default_factory=list)
    info_lines: List[str] = field(default_factory=list)
    menu_items: List[GophermapItem] = field(default_factory=list)


def parse(raw_text: str) -> ParsedGophermap:
    """
    Parse a Gopher menu response into structured items.
    Returns ParsedGophermap.
    """
    result = ParsedGophermap()

    for line in raw_text.splitlines():
        line = line.rstrip("\r\n")
        if line == ".":
            break
        if not line:
            continue

        item_type = line[0]
        rest = line[1:]
        parts = rest.split("\t")

        # Info lines (type 'i') may have fewer parts
        if item_type == "i":
            display = parts[0] if parts else ""
            item = GophermapItem(
                item_type="i",
                display=display,
                selector="",
                host="",
                port=0,
            )
            result.items.append(item)
            result.info_lines.append(display)
            continue

        # All other types need display, selector, host, port
        if len(parts) < 4:
            continue

        try:
            port = int(parts[3]) if parts[3].strip() else 70
        except ValueError:
            port = 70

        item = GophermapItem(
            item_type=item_type,
            display=parts[0],
            selector=parts[1],
            host=parts[2],
            port=port,
        )
        result.items.append(item)
        if item_type != "i":
            result.menu_items.append(item)

    return result
