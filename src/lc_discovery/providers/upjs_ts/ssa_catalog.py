"""Map UPJŠ SSA TAP rows onto the shared discovery catalogue schema."""

from __future__ import annotations

from typing import Any

from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.table import Table

from lc_discovery.catalog_schema import empty_catalog_table, validate_catalog_table
from lc_discovery.lc_key import encode_lc_key
from lc_discovery.shared.tap_ssa_row import (
    object_class_from_ssa_row,
    parse_ssa_location,
    row_value,
)


def map_ssa_row_to_catalog_dict(
    row,
    *,
    provider_id: str,
    distance_arcsec: float,
) -> dict[str, Any] | None:
    """Converts one UPJŠ SSA TAP row to a standard discovery catalogue row dict.

    Args:
        row: TAP result row with SSA columns.
        provider_id (str): Registry slug stored in ``lc_key``.
        distance_arcsec (float): Separation from the search centre in arcseconds.

    Returns:
        dict or None: Standard catalogue row, or ``None`` when ``accref`` is missing.
    """
    accref = row_value(row, "accref")
    if not accref:
        return None

    location = parse_ssa_location(row_value(row, "ssa_location"))
    if location is None:
        return None
    ra_deg, dec_deg = location

    archive_object_id = str(row_value(row, "object_id") or "unknown")
    object_name = str(row_value(row, "ssa_targname") or archive_object_id)
    filter_name = str(row_value(row, "ssa_bandpass") or "unknown")
    collection = row_value(row, "ssa_collection")
    n_points = row_value(row, "ssa_length")
    mean_mag = row_value(row, "mean_mag")
    object_class = object_class_from_ssa_row(row)

    lc_key = encode_lc_key(
        provider_id,
        {
            "accref": str(accref),
            "filter_name": filter_name,
            "object_id": archive_object_id,
        },
    )

    catalog_row: dict[str, Any] = {
        "distance_arcsec": float(distance_arcsec),
        "ra_deg": ra_deg,
        "dec_deg": dec_deg,
        "object_name": object_name,
        "filter_name": filter_name,
        "lc_key": lc_key,
        "t_min": row_value(row, "t_min"),
        "t_max": row_value(row, "t_max"),
        "survey": str(collection) if collection else "UPJŠ",
    }
    if object_class is not None:
        catalog_row["object_class"] = object_class
    if n_points is not None:
        try:
            catalog_row["n_points"] = int(n_points)
        except (TypeError, ValueError):
            pass
    if mean_mag is not None:
        try:
            catalog_row["mag"] = float(mean_mag)
        except (TypeError, ValueError):
            pass
    return catalog_row


def map_ssa_table_to_catalog(
    tap_table: Table,
    *,
    provider_id: str,
    centre_ra_deg: float | None = None,
    centre_dec_deg: float | None = None,
) -> Table:
    """Maps a TAP SSA result table onto the shared discovery catalogue schema.

    Args:
        tap_table (astropy.table.Table): Raw TAP query result.
        provider_id (str): Registry slug for ``lc_key`` encoding.
        centre_ra_deg (float, optional): Search centre RA for separation.
        centre_dec_deg (float, optional): Search centre Dec for separation.

    Returns:
        astropy.table.Table: Validated catalogue table (possibly empty).
    """
    if len(tap_table) == 0:
        return empty_catalog_table()

    centre = None
    if centre_ra_deg is not None and centre_dec_deg is not None:
        centre = SkyCoord(
            ra=float(centre_ra_deg) * u.deg,
            dec=float(centre_dec_deg) * u.deg,
            frame="icrs",
        )

    rows: list[dict[str, Any]] = []
    for row in tap_table:
        location = parse_ssa_location(row_value(row, "ssa_location"))
        if location is None:
            continue
        ra_deg, dec_deg = location
        if centre is not None:
            source = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg, frame="icrs")
            distance_arcsec = centre.separation(source).to_value(u.arcsec)
        else:
            distance_arcsec = 0.0

        catalog_row = map_ssa_row_to_catalog_dict(
            row,
            provider_id=provider_id,
            distance_arcsec=distance_arcsec,
        )
        if catalog_row is not None:
            rows.append(catalog_row)

    if not rows:
        return empty_catalog_table()
    return validate_catalog_table(Table(rows))
