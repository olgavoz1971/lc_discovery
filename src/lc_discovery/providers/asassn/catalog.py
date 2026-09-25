"""Map Sky Patrol discovery metadata onto the shared catalogue schema."""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.table import Table

from lc_discovery.providers.asassn import config
from lc_discovery.catalog_schema import empty_catalog_table, validate_catalog_table
from lc_discovery.lc_key import encode_lc_key
from lc_discovery.shared.gaia_dr3_source_id import format_gaia_source_name

logger = logging.getLogger(__name__)


def _cell_value(row, column: str):
    """Returns one metadata row value when present and finite.

    Args:
        row: Pandas Series or table row.
        column (str): Column name.

    Returns:
        object or None: Cell value.
    """
    if column not in row:
        return None
    value = row[column]
    if value is None or value == "":
        return None
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and np.isnan(value):
        return None
    return value


def _object_name_for_row(row) -> str:
    """Builds a catalogue object label from discovery metadata.

    Args:
        row: Sky Patrol metadata row.

    Returns:
        str: Gaia-style name or ASAS-SN id string.
    """
    gaia_id = _cell_value(row, "gaia_id")
    if gaia_id is not None:
        try:
            return format_gaia_source_name(int(gaia_id))
        except (TypeError, ValueError):
            pass
    asas_sn_id = _cell_value(row, "asas_sn_id")
    if asas_sn_id is not None:
        return f"ASAS-SN {int(asas_sn_id)}"
    return "ASAS-SN source"


def map_metadata_row_to_catalog_rows(
    row,
    *,
    provider_id: str,
    distance_arcsec: float,
) -> list[dict[str, Any]]:
    """Expands one Sky Patrol metadata row into two candidate band rows.

    Args:
        row: Discovery metadata for one source.
        provider_id (str): Registry slug for ``lc_key``.
        distance_arcsec (float): Separation from search centre in arcseconds.

    Returns:
        list[dict]: Two catalogue dicts (``g`` and ``V`` candidates).
    """
    asas_sn_id = _cell_value(row, "asas_sn_id")
    ra_val = _cell_value(row, "ra_deg")
    dec_val = _cell_value(row, "dec_deg")
    if asas_sn_id is None or ra_val is None or dec_val is None:
        return []

    pstarrs_g_mag = _cell_value(row, "pstarrs_g_mag")
    object_name = _object_name_for_row(row)
    rows: list[dict[str, Any]] = []

    for band in config.ASASSN_BANDS:
        lc_key = encode_lc_key(
            provider_id,
            {
                "asas_sn_id": str(int(asas_sn_id)),
                "band": band.band_code,
            },
        )
        catalog_row: dict[str, Any] = {
            "distance_arcsec": float(distance_arcsec),
            "ra_deg": float(ra_val),
            "dec_deg": float(dec_val),
            "object_name": object_name,
            "filter_name": band.filter_name,
            "lc_key": lc_key,
            "survey": config.ASASSN_SURVEY,
            "provider_note": config.DISCOVERY_CATALOG_PROVIDER_NOTE,
        }
        if band.band_code == "g" and pstarrs_g_mag is not None:
            try:
                catalog_row["mag"] = float(pstarrs_g_mag)
            except (TypeError, ValueError):
                pass
        rows.append(catalog_row)
    return rows


def map_metadata_table_to_catalog(
    metadata: Table | Any,
    *,
    provider_id: str,
    centre_ra_deg: float | None = None,
    centre_dec_deg: float | None = None,
) -> Table:
    """Maps Sky Patrol discovery metadata onto the standard catalogue schema.

    Args:
        metadata (pandas.DataFrame or astropy.table.Table): Discovery query result.
        provider_id (str): Registry slug.
        centre_ra_deg (float, optional): Cone centre RA for separation.
        centre_dec_deg (float, optional): Cone centre Dec for separation.

    Returns:
        astropy.table.Table: Validated catalogue (possibly empty).
    """
    import pandas as pd

    if isinstance(metadata, pd.DataFrame):
        if len(metadata) == 0:
            return empty_catalog_table()
        frame = metadata
    elif isinstance(metadata, Table):
        if len(metadata) == 0:
            return empty_catalog_table()
        frame = metadata.to_pandas()
    else:
        raise TypeError(f"Expected DataFrame or Table, got {type(metadata)!r}")

    centre = None
    if centre_ra_deg is not None and centre_dec_deg is not None:
        centre = SkyCoord(
            ra=float(centre_ra_deg) * u.deg,
            dec=float(centre_dec_deg) * u.deg,
            frame="icrs",
        )

    rows: list[dict[str, Any]] = []
    for _, series in frame.iterrows():
        ra_val = _cell_value(series, "ra_deg")
        dec_val = _cell_value(series, "dec_deg")
        if ra_val is None or dec_val is None:
            continue
        if centre is not None:
            source = SkyCoord(ra=float(ra_val) * u.deg, dec=float(dec_val) * u.deg, frame="icrs")
            distance_arcsec = centre.separation(source).to_value(u.arcsec)
        else:
            distance_arcsec = 0.0
        rows.extend(
            map_metadata_row_to_catalog_rows(
                series,
                provider_id=provider_id,
                distance_arcsec=distance_arcsec,
            )
        )

    if not rows:
        return empty_catalog_table()
    return validate_catalog_table(Table(rows))
