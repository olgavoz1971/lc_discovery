"""ADQL formatting helpers shared by TAP mission providers."""

from __future__ import annotations

import math


def adql_top_limit_clause(row_limit: int | None) -> str:
    """Builds an ADQL ``TOP`` prefix for ``SELECT`` statements.

    Args:
        row_limit (int, optional): Maximum number of rows to return. When ``None``,
            no ``TOP`` clause is emitted.

    Returns:
        str: Empty string or ``"TOP n "`` suitable after ``SELECT``.

    Raises:
        ValueError: When ``row_limit`` is not a positive integer.
    """
    if row_limit is None:
        return ""
    limit = int(row_limit)
    if limit <= 0:
        raise ValueError(f"ADQL row limit must be positive, got {row_limit!r}.")
    return f"TOP {limit} "


def adql_icrs_ra_dec_box_clauses(
    *,
    ra_deg: float,
    dec_deg: float,
    radius_arcsec: float,
    ra_column: str,
    dec_column: str,
) -> str:
    """Builds ADQL predicates for an ICRS ra/dec box around a cone centre.

    Gaia@AIP ``gaia_source`` cone queries using ``CONTAINS(POINT, CIRCLE)``
    alone can exceed TAP statement timeouts; a ra/dec box prefilter uses indexed
    columns and is a conservative superset of the cone for small discovery radii.

    Args:
        ra_deg (float): Cone centre right ascension in degrees.
        dec_deg (float): Cone centre declination in degrees.
        radius_arcsec (float): Cone radius in arcseconds.
        ra_column (str): Qualified ADQL column name for right ascension.
        dec_column (str): Qualified ADQL column name for declination.

    Returns:
        str: ADQL predicate fragment joining ra and dec range tests with ``AND``.
    """
    radius_deg = float(radius_arcsec) / 3600.0
    ra = float(ra_deg)
    dec = float(dec_deg)
    dec_min = dec - radius_deg
    dec_max = dec + radius_deg
    cos_dec = max(abs(math.cos(math.radians(dec))), 1e-6)
    ra_extent = radius_deg / cos_dec
    ra_min = ra - ra_extent
    ra_max = ra + ra_extent
    return (
        f"{ra_column} BETWEEN {ra_min} AND {ra_max} "
        f"AND {dec_column} BETWEEN {dec_min} AND {dec_max}"
    )
