"""Mission coverage declaration, modelled on the VO Registry ``vs:Coverage``.

The model follows IVOA VODataService 1.2 (section 3.2, "Coverage in Space,
Time, and Spectrum") and the RegTAP 1.2 tables ``rr.stc_spatial``,
``rr.stc_temporal`` and ``rr.stc_spectral``. One spatial and one temporal
coverage describe a whole mission, as in the Registry.

References:
    https://www.ivoa.net/documents/VODataService/20211102/REC-VODataService-1.2.html
    https://www.ivoa.net/documents/RegTAP/20241002/REC-RegTAP-1.2.html
    https://www.ivoa.net/documents/MOC/index.html
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

logger = logging.getLogger(__name__)

Interval = tuple[float, float]

ALL_SKY_MOC = "0/0-11"
"""The whole sky as an IVOA MOC string (order 0, all 12 cells), as written in VODataService 1.2."""

WAVEBAND_OPTICAL = ("Optical",)
"""The optical term of the IVOA messenger vocabulary, as written in VODataService 1.2."""

ONGOING_MJD_END = 100000.0
"""Upper limit of the temporal coverage of an ongoing mission (the Registry convention)."""


@dataclass(frozen=True)
class MissionCoverage:
    """Coverage of a whole mission in space, time and spectrum.

    Every field must be given. ``None`` means "unknown" and is written
    explicitly by the provider; it is never a reason to skip a mission.

    Attributes:
        spatial (str or None): IVOA MOC in the ASCII serialisation, ICRS
            (for example ``"0/0-11"`` for the whole sky).
        temporal (tuple of (float, float) or None): Intervals in MJD (TDB),
            a union. Limits are whole days, rounded outward; ``100000`` is
            the upper limit of an ongoing mission.
        spectral (tuple of (float, float) or None): Intervals in joules
            (messenger energy), a union.
        waveband (tuple of str or None): Terms of the IVOA messenger
            vocabulary (for example ``"Optical"``).
    """

    spatial: str | None
    temporal: tuple[Interval, ...] | None
    spectral: tuple[Interval, ...] | None
    waveband: tuple[str, ...] | None


def _check_intervals(
    mission_id: str,
    field: str,
    intervals: object,
    *,
    whole_days: bool,
) -> None:
    """Validates a union of numeric intervals.

    Args:
        mission_id (str): Mission slug for the error message.
        field (str): Field name for the error message.
        intervals (object): Value to check.
        whole_days (bool): When True, the limits must be whole numbers.

    Raises:
        ValueError: When the value is not a non-empty tuple of ordered,
            finite pairs (and whole numbers when requested).
    """
    where = f"Mission '{mission_id}': coverage.{field}"
    if not isinstance(intervals, tuple) or not intervals:
        raise ValueError(f"{where} must be None or a non-empty tuple of (start, end) pairs.")
    for pair in intervals:
        if not isinstance(pair, tuple) or len(pair) != 2:
            raise ValueError(f"{where} must contain (start, end) pairs, got {pair!r}.")
        start, end = pair
        for value in (start, end):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{where} limits must be numbers, got {value!r}.")
            if not math.isfinite(value):
                raise ValueError(f"{where} limits must be finite, got {value!r}.")
            if whole_days and float(value) != math.floor(value):
                raise ValueError(f"{where} limits must be whole days, got {value!r}.")
        if start > end:
            raise ValueError(f"{where} interval start is after its end: {pair!r}.")


def validate_coverage(mission_id: str, coverage: object) -> MissionCoverage:
    """Checks the structure of a provider's coverage declaration.

    The MOC string is not parsed (no MOC library is required); it only has
    to be a non-empty string.

    Args:
        mission_id (str): Mission slug for the error message.
        coverage (object): Value of the provider's ``coverage`` attribute.

    Returns:
        MissionCoverage: The same object, once checked.

    Raises:
        ValueError: When the value is not a ``MissionCoverage`` or a field
            has the wrong type or an invalid value.
    """
    if not isinstance(coverage, MissionCoverage):
        raise ValueError(f"Mission '{mission_id}': 'coverage' must be a MissionCoverage.")
    if coverage.spatial is not None and (
        not isinstance(coverage.spatial, str) or not coverage.spatial.strip()
    ):
        raise ValueError(f"Mission '{mission_id}': coverage.spatial must be None or a non-empty string.")
    if coverage.temporal is not None:
        _check_intervals(mission_id, "temporal", coverage.temporal, whole_days=True)
    if coverage.spectral is not None:
        _check_intervals(mission_id, "spectral", coverage.spectral, whole_days=False)
        if any(start <= 0 for start, _ in coverage.spectral):
            raise ValueError(f"Mission '{mission_id}': coverage.spectral limits must be positive.")
    if coverage.waveband is not None:
        terms = coverage.waveband
        if (
            not isinstance(terms, tuple)
            or not terms
            or any(not isinstance(t, str) or not t.strip() for t in terms)
        ):
            raise ValueError(
                f"Mission '{mission_id}': coverage.waveband must be None or a non-empty tuple of strings."
            )
    return coverage
