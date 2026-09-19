"""
REFInet Pillar — Money is an integer

Every amount is an integer count of the asset's smallest unit, stored as
TEXT. Two reasons it is not a number column:

  * REFI has 18 decimals. A float64 cannot hold 1e18 exactly, and a ledger
    that rounds is not a ledger.
  * SQLite's INTEGER is i64, so 1e19 overflows it.

So amounts are folded here, with Python ``int``, and never with SQL
``SUM()``. An asset is identified by chain id and contract address (the
zero address for a native coin) plus its decimals.
"""

from __future__ import annotations

ZERO_ADDRESS = "0x" + "0" * 40


def asset(chain_id: int, address: str = ZERO_ADDRESS, decimals: int = 18) -> dict:
    """Build an asset descriptor."""
    return {"chain_id": int(chain_id), "address": address, "decimals": int(decimals)}


def asset_key(row) -> tuple:
    """The identity of the asset a row is denominated in."""
    get = row.get if hasattr(row, "get") else row.__getitem__
    return (get("asset_chain_id"), (get("asset_address") or "").lower(),
            get("asset_decimals"))


def to_units(amount: str | int | None) -> int:
    """Parse a stored base-unit amount. Missing or blank reads as zero."""
    if amount is None or amount == "":
        return 0
    return int(str(amount))


def fold_units(rows, field: str = "amount_units") -> int:
    """Total a set of rows, in base units, with exact integer arithmetic."""
    total = 0
    for row in rows:
        get = row.get if hasattr(row, "get") else row.__getitem__
        try:
            total += to_units(get(field))
        except (KeyError, IndexError):
            continue
    return total


def fold_by_asset(rows, field: str = "amount_units") -> dict[tuple, int]:
    """Total per asset — amounts in different assets are never added."""
    totals: dict[tuple, int] = {}
    for row in rows:
        get = row.get if hasattr(row, "get") else row.__getitem__
        try:
            value = to_units(get(field))
        except (KeyError, IndexError):
            continue
        totals[asset_key(row)] = totals.get(asset_key(row), 0) + value
    return totals


def format_units(units: str | int | None, decimals: int = 18,
                 precision: int = 6) -> str:
    """Render base units for display only. Never feed this back into a ledger."""
    value = to_units(units)
    if decimals <= 0:
        return str(value)
    sign = "-" if value < 0 else ""
    value = abs(value)
    whole, frac = divmod(value, 10 ** decimals)
    frac_text = str(frac).rjust(decimals, "0")[:precision].rstrip("0")
    return f"{sign}{whole}.{frac_text}" if frac_text else f"{sign}{whole}"
