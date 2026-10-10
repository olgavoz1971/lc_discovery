"""Lightkurve MAST search for TESS archive products."""

from __future__ import annotations

import logging

from astropy.coordinates import SkyCoord
from astropy.table import Table
from astropy import units as u

from lc_discovery.providers.tess import config

logger = logging.getLogger(__name__)


def _import_lightkurve():
    """Imports Lightkurve on demand.

    Returns:
        module: The ``lightkurve`` module.

    Raises:
        ImportError: When the optional ``tess`` extra is not installed.
    """
    try:
        import lightkurve as lk
    except ImportError as exc:
        raise ImportError(
            f"{config.DISPLAY_NAME} requires the optional extra 'tess' "
            "(pip install 'lc_discovery[tess]')."
        ) from exc
    return lk


def search_by_tic(tic: int) -> Table:
    """Searches MAST for all TESS archive light curves of one TIC.

    Args:
        tic (int): TESS Input Catalogue number.

    Returns:
        astropy.table.Table: Lightkurve ``SearchResult.table`` (possibly empty).
    """
    lk = _import_lightkurve()
    target = config.format_tic_name(tic)
    logger.info("%s MAST search target=%s", config.DISPLAY_NAME, target)
    result = lk.search_lightcurve(target, mission="TESS")
    table = result.table if result is not None else Table()
    logger.info("%s MAST returned %s product(s) for %s", config.DISPLAY_NAME, len(table), target)
    return table


def search_cone(ra_deg: float, dec_deg: float, radius_arcsec: float) -> Table:
    """Searches MAST for TESS archive light curves in a cone.

    All products in the cone are returned. The closest TIC is not selected.

    Args:
        ra_deg (float): ICRS right ascension in degrees.
        dec_deg (float): ICRS declination in degrees.
        radius_arcsec (float): Cone radius in arcseconds.

    Returns:
        astropy.table.Table: Lightkurve ``SearchResult.table`` (possibly empty).
    """
    lk = _import_lightkurve()
    coord = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg)
    radius = radius_arcsec * u.arcsec
    logger.info(
        "%s MAST cone ra=%s dec=%s radius_arcsec=%s",
        config.DISPLAY_NAME,
        ra_deg,
        dec_deg,
        radius_arcsec,
    )
    result = lk.search_lightcurve(coord, radius=radius, mission="TESS")
    table = result.table if result is not None else Table()
    logger.info("%s MAST cone returned %s product(s)", config.DISPLAY_NAME, len(table))
    return table
