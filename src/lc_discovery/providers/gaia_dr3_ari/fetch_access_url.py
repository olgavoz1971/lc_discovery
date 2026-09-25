"""Fetch Gaia DR3 (ARI) epoch photometry VOTables (datalink or direct URL)."""

from __future__ import annotations

import io
import logging
import urllib.error
import urllib.request

from lc_discovery.providers.gaia_dr3_ari.datalink import build_timeseries_datalink_url
from skvo_veb.utils.my_tools import PipeException
from volightcurve import VOLightCurve

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_SEC = 120


def fetch_votable_bytes(
    access_url: str,
    *,
    timeout_sec: float = _DEFAULT_TIMEOUT_SEC,
) -> bytes:
    """Downloads one bundled Gaia DR3 VOTable.

    Args:
        access_url (str): Absolute HTTP(S) URL of the timeseries product.
        timeout_sec (float): Network read timeout in seconds.

    Returns:
        bytes: Archive VOTable, before enrichment.

    Raises:
        PipeException: When the URL is missing or the download fails.
    """
    url = str(access_url or "").strip()
    if not url:
        raise PipeException("Lightcurve access_url is empty.")

    try:
        request = urllib.request.Request(url, headers={"User-Agent": "lc_discovery"})
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            payload = response.read()
    except urllib.error.URLError as exc:
        logger.warning("access_url download failed url=%s: %s", url, exc)
        raise PipeException(f"Failed to download lightcurve from access_url: {exc}") from exc

    logger.info("Fetched Gaia DR3 ARI VOTable url=%s nbytes=%s", url, len(payload))
    return payload


def fetch_volightcurve_from_access_url(
    access_url: str,
    *,
    table_id: int,
    timeout_sec: float = _DEFAULT_TIMEOUT_SEC,
) -> VOLightCurve:
    """Downloads one bundled Gaia DR3 VOTable and selects a band table.

    Args:
        access_url (str): Absolute HTTP(S) URL from ObsCore ``access_url``.
        table_id (int): Zero-based Astropy table index (G=0, BP=1, RP=2).
        timeout_sec (float): Network read timeout in seconds.

    Returns:
        VOLightCurve: Parsed single-band VO lightcurve.

    Raises:
        PipeException: When the URL is missing or the download/parse fails.
    """
    url = str(access_url or "").strip()
    payload = fetch_votable_bytes(url, timeout_sec=timeout_sec)
    try:
        volc = VOLightCurve(io.BytesIO(payload), table_id=int(table_id))
    except Exception as exc:
        logger.warning(
            "access_url VOTable parse failed url=%s table_id=%s: %s",
            url,
            table_id,
            exc,
        )
        raise PipeException(f"Downloaded access_url is not a valid lightcurve: {exc}") from exc

    logger.info(
        "Fetched Gaia DR3 ARI lightcurve url=%s table_id=%s n_points=%s",
        url,
        table_id,
        len(volc),
    )
    return volc


def fetch_volightcurve_from_timeseries_datalink(
    source_id: int | str,
    *,
    table_id: int,
    timeout_sec: float = _DEFAULT_TIMEOUT_SEC,
) -> VOLightCurve:
    """Downloads one band via the Heidelberg Gaia DR3 timeseries datalink.

    Args:
        source_id (int or str): Gaia DR3 ``source_id``.
        table_id (int): Zero-based Astropy table index (G=0, BP=1, RP=2).
        timeout_sec (float): Network read timeout in seconds.

    Returns:
        VOLightCurve: Parsed single-band VO lightcurve.

    Raises:
        PipeException: When the download or parse fails.
    """
    url = build_timeseries_datalink_url(source_id)
    return fetch_volightcurve_from_access_url(
        url,
        table_id=table_id,
        timeout_sec=timeout_sec,
    )
