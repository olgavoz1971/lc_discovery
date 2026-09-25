"""IRSA TAP discovery queries for ZTF DR24 object metadata."""

from __future__ import annotations

import logging

import pandas as pd
from astroquery.ipac.irsa import Irsa

from lc_discovery.providers.ztf import config
from skvo_veb.utils.my_tools import PipeException

logger = logging.getLogger(__name__)


def _tap_result_to_frame(result) -> pd.DataFrame:
    """Converts an astroquery TAP result to a pandas DataFrame.

    Args:
        result: Return value from ``Irsa.query_tap``.

    Returns:
        pandas.DataFrame: Parsed rows (possibly empty).
    """
    if result is None or len(result) == 0:
        return pd.DataFrame()
    return result.to_table().to_pandas()


def query_objects_cone(
    *,
    ra_deg: float,
    dec_deg: float,
    radius_arcsec: float,
) -> pd.DataFrame:
    """Runs a cone search on ``ztf_objects_dr24`` via IRSA TAP.

    Args:
        ra_deg (float): Cone centre ICRS right ascension in degrees.
        dec_deg (float): Cone centre ICRS declination in degrees.
        radius_arcsec (float): Cone radius in arcseconds.

    Returns:
        pandas.DataFrame: Metadata rows (no epoch download).

    Raises:
        PipeException: When the TAP query fails.
    """
    radius_deg = float(radius_arcsec) / 3600.0
    columns = ", ".join(config.DISCOVERY_TAP_COLUMNS)
    query = f"""
    SELECT {columns}
    FROM {config.OBJECTS_TABLE}
    WHERE CONTAINS(
        POINT('ICRS', ra, dec),
        CIRCLE('ICRS', {float(ra_deg)}, {float(dec_deg)}, {radius_deg})
    ) = 1
    """
    logger.info(
        "%s TAP cone ra=%.6f dec=%.6f radius_arcsec=%.3f",
        config.DISPLAY_NAME,
        ra_deg,
        dec_deg,
        radius_arcsec,
    )
    try:
        return _tap_result_to_frame(Irsa.query_tap(query=query))
    except Exception as exc:
        raise PipeException(f"{config.DISPLAY_NAME}: IRSA TAP cone query failed: {exc}") from exc


def query_objects_by_oid(oid: int | str) -> pd.DataFrame:
    """Fetches one ZTF OID row from ``ztf_objects_dr24``.

    Args:
        oid (int or str): ZTF object/lightcurve identifier.

    Returns:
        pandas.DataFrame: Zero or one metadata rows.

    Raises:
        PipeException: When the TAP query fails.
    """
    oid_int = int(oid)
    columns = ", ".join(config.DISCOVERY_TAP_COLUMNS)
    query = f"""
    SELECT {columns}
    FROM {config.OBJECTS_TABLE}
    WHERE oid = {oid_int}
    """
    logger.info("%s TAP lookup oid=%s", config.DISPLAY_NAME, oid_int)
    try:
        return _tap_result_to_frame(Irsa.query_tap(query=query))
    except Exception as exc:
        raise PipeException(f"{config.DISPLAY_NAME}: IRSA TAP oid query failed: {exc}") from exc
