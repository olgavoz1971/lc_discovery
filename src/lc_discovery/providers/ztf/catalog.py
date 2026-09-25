"""Map ZTF TAP discovery rows onto the shared catalogue schema."""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.table import Table

from lc_discovery.catalog_schema import empty_catalog_table, validate_catalog_table
from lc_discovery.lc_key import encode_lc_key
from lc_discovery.providers.ztf import config

logger = logging.getLogger(__name__)


def _cell_value(row, column: str):
    """Returns one metadata row value when present and finite.

    Args:
        row: Pandas Series or mapping row.
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


def filter_discovery_frame_with_epochs(frame):
    """Removes TAP rows with no epoch photometry (``nobsrel`` zero or missing).

    Args:
        frame (pandas.DataFrame): IRSA ``ztf_objects_dr24`` discovery result.

    Returns:
        pandas.DataFrame: Rows that report at least one epoch.
    """
    import pandas as pd

    if not isinstance(frame, pd.DataFrame) or len(frame) == 0:
        return frame
    if "nobsrel" not in frame.columns:
        logger.warning(
            "%s discovery frame missing nobsrel; cannot filter empty lightcurves.",
            config.DISPLAY_NAME,
        )
        return frame

    nobs = pd.to_numeric(frame["nobsrel"], errors="coerce")
    keep = nobs.notna() & (nobs > 0)
    dropped = int((~keep).sum())
    if dropped:
        logger.info(
            "%s discovery omitted %s OID row(s) with nobsrel <= 0 or invalid.",
            config.DISPLAY_NAME,
            dropped,
        )
    return frame.loc[keep].copy()


def map_discovery_row_to_catalog_row(
    row,
    *,
    provider_id: str,
    distance_arcsec: float,
) -> dict[str, Any] | None:
    """Maps one TAP metadata row to a standard catalogue dict.

    Args:
        row: Discovery metadata for one OID.
        provider_id (str): Registry slug for ``lc_key``.
        distance_arcsec (float): Separation from the search centre in arcseconds.

    Returns:
        dict or None: Catalogue row fields when mandatory columns are present.
    """
    oid_val = _cell_value(row, "oid")
    ra_val = _cell_value(row, "ra")
    dec_val = _cell_value(row, "dec")
    filtercode = _cell_value(row, "filtercode")
    if oid_val is None or ra_val is None or dec_val is None or filtercode is None:
        return None

    try:
        band = config.band_spec_for_filtercode(str(filtercode))
    except ValueError:
        logger.warning(
            "%s skipping unsupported filtercode=%r oid=%s",
            config.DISPLAY_NAME,
            filtercode,
            oid_val,
        )
        return None

    nobs = _cell_value(row, "nobsrel")
    if nobs is None:
        return None
    try:
        n_points = int(nobs)
    except (TypeError, ValueError):
        return None
    if n_points <= 0:
        return None

    oid_int = int(oid_val)
    lc_key = encode_lc_key(provider_id, {"oid": str(oid_int)})
    catalog_row: dict[str, Any] = {
        "distance_arcsec": float(distance_arcsec),
        "ra_deg": float(ra_val),
        "dec_deg": float(dec_val),
        "object_name": config.format_ztf_oid_name(oid_int),
        "filter_name": band.filter_name,
        "filter_identifier": band.filter_identifier,
        "lc_key": lc_key,
        "survey": config.ZTF_SURVEY,
        "n_points": n_points,
    }
    meanmag = _cell_value(row, "meanmag")
    if meanmag is not None:
        try:
            catalog_row["mag"] = float(meanmag)
        except (TypeError, ValueError):
            pass
    return catalog_row


def map_discovery_frame_to_catalog(
    frame,
    *,
    provider_id: str,
    centre_ra_deg: float | None = None,
    centre_dec_deg: float | None = None,
) -> Table:
    """Maps TAP discovery metadata onto the standard catalogue schema.

    Args:
        frame (pandas.DataFrame): TAP query result.
        provider_id (str): Registry slug.
        centre_ra_deg (float, optional): Cone centre RA for separation.
        centre_dec_deg (float, optional): Cone centre Dec for separation.

    Returns:
        astropy.table.Table: Validated catalogue (possibly empty).
    """
    import pandas as pd

    if not isinstance(frame, pd.DataFrame) or len(frame) == 0:
        return empty_catalog_table()

    centre = None
    if centre_ra_deg is not None and centre_dec_deg is not None:
        centre = SkyCoord(
            ra=float(centre_ra_deg) * u.deg,
            dec=float(centre_dec_deg) * u.deg,
            frame="icrs",
        )

    rows: list[dict[str, Any]] = []
    for _, series in frame.iterrows():
        ra_val = _cell_value(series, "ra")
        dec_val = _cell_value(series, "dec")
        if ra_val is None or dec_val is None:
            continue
        if centre is not None:
            source = SkyCoord(
                ra=float(ra_val) * u.deg,
                dec=float(dec_val) * u.deg,
                frame="icrs",
            )
            distance_arcsec = centre.separation(source).to_value(u.arcsec)
        else:
            distance_arcsec = 0.0
        mapped = map_discovery_row_to_catalog_row(
            series,
            provider_id=provider_id,
            distance_arcsec=distance_arcsec,
        )
        if mapped is not None:
            rows.append(mapped)

    if not rows:
        return empty_catalog_table()
    return validate_catalog_table(Table(rows))
