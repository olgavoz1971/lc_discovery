"""Shared helpers for reading and parsing SSA TAP ``ts_ssa`` result rows."""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_SSA_LOCATION_PATTERN = re.compile(
    r"^[\[\(]\s*"
    r"([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*[, ]\s*"
    r"([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*"
    r"[\]\)]$"
)


def row_value(row, key: str) -> Any:
    """Returns a catalogue field from an Astropy row or dict.

    Args:
        row: TAP result row.
        key (str): Column name.

    Returns:
        Any: Cell value or ``None``.
    """
    if hasattr(row, "colnames"):
        if key not in row.colnames:
            return None
        value = row[key]
    else:
        value = row.get(key)
    if value is None:
        return None
    try:
        import numpy as np

        if isinstance(value, np.generic):
            value = value.item()
        if value is np.ma.masked:
            return None
        if hasattr(value, "mask") and np.any(value.mask):
            return None
    except Exception:
        pass
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value


def parse_ssa_location(value: Any) -> tuple[float, float] | None:
    """Parses ``ssa_location`` into ICRS ``(ra_deg, dec_deg)``.

    Handles parenthesis text ``(RA, Dec)`` and numeric pair columns (list, tuple,
    or masked arrays) returned by some TAP services.

    Args:
        value: SSA location field from a TAP row.

    Returns:
        tuple[float, float] or None: Sky position in degrees when parseable.
    """
    if value is None:
        return None

    try:
        import numpy as np

        if isinstance(value, np.ndarray):
            flat = np.asarray(value, dtype=float).ravel()
            if flat.size >= 2 and np.all(np.isfinite(flat[:2])):
                return float(flat[0]), float(flat[1])
    except (TypeError, ValueError):
        pass

    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            return float(value[0]), float(value[1])
        except (TypeError, ValueError):
            return None

    text = str(value).strip()
    match = _SSA_LOCATION_PATTERN.match(text)
    if match:
        return float(match.group(1)), float(match.group(2))

    logger.warning("Unrecognised ssa_location format: %r", value)
    return None


def object_class_from_ssa_row(row) -> str | None:
    """Returns the Simbad object-type string from ``ssa_targclass`` when present.

    Args:
        row: TAP SSA result row.

    Returns:
        str or None: Object class label for the discovery catalogue.
    """
    targclass = row_value(row, "ssa_targclass")
    if targclass is None:
        return None
    label = str(targclass).strip()
    return label or None
