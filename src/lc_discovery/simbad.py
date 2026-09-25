"""Simbad resolve payload passed into a mission search."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SimbadResolveResult:
    """Normalised Simbad response for search orchestration.

    Attributes:
        query_name (str): User-supplied name passed to Simbad.
        main_id (str): Simbad main identifier.
        identifiers (tuple[str, ...]): Cross-identifiers returned by Simbad.
        ra_deg (float): ICRS right ascension in degrees.
        dec_deg (float): ICRS declination in degrees.
    """

    query_name: str
    main_id: str
    identifiers: tuple[str, ...]
    ra_deg: float
    dec_deg: float
