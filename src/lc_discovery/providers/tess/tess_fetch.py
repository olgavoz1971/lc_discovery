"""Download one TESS archive light curve identified by TIC, sector, author, cadence."""

from __future__ import annotations

import logging

from lc_discovery.providers.tess import archive_cache, config
from lc_discovery.providers.tess.mast_search import _import_lightkurve

logger = logging.getLogger(__name__)


def _unique_search_result(*, tic: int, sector: int, author: str, exptime: float):
    """Searches MAST for the unique product with the given identity.

    Args:
        tic (int): TESS Input Catalogue number.
        sector (int): TESS sector.
        author (str): Pipeline author tag.
        exptime (float): MAST cadence in seconds.

    Returns:
        lightkurve.SearchResult: One-row result.

    Raises:
        ValueError: When no product or more than one product matches.
    """
    lk = _import_lightkurve()
    target = config.format_tic_name(tic)
    result = lk.search_lightcurve(
        target,
        mission="TESS",
        author=author,
        sector=int(sector),
        exptime=float(exptime),
    )
    n_hit = 0 if result is None else len(result)
    if n_hit == 0:
        raise ValueError(
            f"{config.DISPLAY_NAME}: no product for {target} sector {sector} "
            f"author {author} exptime {exptime:g} s."
        )
    if n_hit > 1:
        raise ValueError(
            f"{config.DISPLAY_NAME}: {n_hit} products for {target} sector {sector} "
            f"author {author} exptime {exptime:g} s; expected one."
        )
    return result


def download_archive_product(
    *,
    tic: int,
    sector: int,
    author: str,
    exptime: float,
    search_result=None,
):
    """Obtains one readable archive light curve and its FITS pointer.

    The shared Lightkurve cache is used; a truncated cached file is purged and
    downloaded once more. A host that already holds the one-row search result
    for this product can pass it to skip a second MAST search.

    Args:
        tic (int): TESS Input Catalogue number.
        sector (int): TESS sector.
        author (str): Pipeline author tag.
        exptime (float): MAST cadence in seconds.
        search_result (optional): One-row Lightkurve ``SearchResult`` of this
            product. When omitted, MAST is searched.

    Returns:
        tuple: ``(lightkurve LightCurve, pointer dict)`` where the pointer has
        ``obs_collection``, ``obs_id`` and ``product_filename``.

    Raises:
        ValueError: When the product is missing, not unique, or unreadable, or
            when ``search_result`` does not have exactly one row.
    """
    logger.info(
        "%s fetch TIC=%s sector=%s author=%s exptime=%s",
        config.DISPLAY_NAME,
        tic,
        sector,
        author,
        exptime,
    )
    if search_result is None:
        search_result = _unique_search_result(
            tic=tic, sector=sector, author=author, exptime=exptime
        )
    elif len(search_result) != 1:
        raise ValueError(
            f"{config.DISPLAY_NAME}: expected a one-row search result, "
            f"got {len(search_result)} rows."
        )
    return archive_cache.read_with_repair(search_result, author=author)


def download_archive_lightcurve(*, tic: int, sector: int, author: str, exptime: float):
    """Downloads the unique MAST product and returns the light curve only.

    Args:
        tic (int): TESS Input Catalogue number.
        sector (int): TESS sector.
        author (str): Pipeline author tag.
        exptime (float): MAST cadence in seconds.

    Returns:
        object: Lightkurve ``LightCurve``.

    Raises:
        ValueError: As for ``download_archive_product``.
    """
    lc, _pointer = download_archive_product(
        tic=tic, sector=sector, author=author, exptime=exptime
    )
    return lc


def redownload_archive_product(*, tic: int, sector: int, author: str, exptime: float, search_result=None):
    """Purges the cached FITS of one product and fetches it again from MAST.

    Args:
        tic (int): TESS Input Catalogue number.
        sector (int): TESS sector.
        author (str): Pipeline author tag.
        exptime (float): MAST cadence in seconds.
        search_result (optional): One-row Lightkurve ``SearchResult``.

    Returns:
        tuple: ``(was_purged bool, lightkurve LightCurve, pointer dict)``.

    Raises:
        ValueError: As for ``download_archive_product``.
    """
    if search_result is None:
        search_result = _unique_search_result(
            tic=tic, sector=sector, author=author, exptime=exptime
        )
    was_purged = archive_cache.purge(archive_cache.product_pointer(search_result))
    lc, pointer = archive_cache.read_with_repair(search_result, author=author)
    return was_purged, lc, pointer


def purge_archive_product(*, tic: int, sector: int, author: str, exptime: float, search_result=None) -> bool:
    """Deletes the cached FITS of one product without downloading it again.

    Args:
        tic (int): TESS Input Catalogue number.
        sector (int): TESS sector.
        author (str): Pipeline author tag.
        exptime (float): MAST cadence in seconds.
        search_result (optional): One-row Lightkurve ``SearchResult``.

    Returns:
        bool: True when a file was deleted, False when none was cached.

    Raises:
        ValueError: When the product is missing or not unique.
    """
    if search_result is None:
        search_result = _unique_search_result(
            tic=tic, sector=sector, author=author, exptime=exptime
        )
    return archive_cache.purge(archive_cache.product_pointer(search_result))
