"""Parse Gaia AIP TAP array-valued epoch-photometry columns."""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


def parse_array_column(value: Any) -> list[float]:
    """Normalises one TAP array column to a plain Python float list.

    Args:
        value: TAP cell value (masked array, ndarray, list, scalar, or string).

    Returns:
        list[float]: Parsed values; invalid entries become ``nan``.
    """
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        text = value.decode("utf-8") if isinstance(value, bytes) else value
        text = text.strip()
        if not text:
            return []
        parts = text.split()
        return [float(part) for part in parts]

    if np.isscalar(value):
        try:
            scalar = float(value)
        except (TypeError, ValueError):
            return []
        return [scalar]

    try:
        array = np.asarray(value, dtype=float).ravel()
    except (TypeError, ValueError):
        logger.warning("Could not parse array column value of type %s", type(value))
        return []

    result: list[float] = []
    for item in array:
        if isinstance(item, np.generic):
            item = item.item()
        if item is np.ma.masked:
            result.append(float("nan"))
            continue
        try:
            result.append(float(item))
        except (TypeError, ValueError):
            result.append(float("nan"))
    return result
