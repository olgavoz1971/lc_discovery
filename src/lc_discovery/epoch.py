"""Catalogue folding-epoch helpers."""

from __future__ import annotations

import math

# Modified Julian Date offset: MJD = JD - 2400000.5.
JD_TO_MJD = 2400000.5

__all__ = ["JD_TO_MJD", "resolve_catalog_epoch"]


def resolve_catalog_epoch(epoch) -> float | None:
    """Normalises a catalogue folding epoch.

    A value of ``0`` is treated as missing.

    Args:
        epoch: Raw epoch from a catalogue row.

    Returns:
        float or None: Julian Date epoch, or ``None`` when missing.
    """
    if epoch is None:
        return None
    try:
        value = float(epoch)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value == 0:
        return None
    return value
