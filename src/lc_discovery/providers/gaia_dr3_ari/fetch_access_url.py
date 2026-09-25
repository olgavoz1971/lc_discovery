"""Fetch Gaia DR3 (ARI) epoch photometry VOTables (datalink or direct URL)."""

from __future__ import annotations

import logging
import urllib.error
import urllib.request

from lc_discovery.providers.gaia_dr3_ari.datalink import build_timeseries_datalink_url

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
        ValueError: When the URL is missing or the download fails.
    """
    url = str(access_url or "").strip()
    if not url:
        raise ValueError("Lightcurve access_url is empty.")

    try:
        request = urllib.request.Request(url, headers={"User-Agent": "lc_discovery"})
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            payload = response.read()
    except urllib.error.URLError as exc:
        logger.warning("access_url download failed url=%s: %s", url, exc)
        raise ValueError(f"Failed to download lightcurve from access_url: {exc}") from exc

    logger.info("Fetched Gaia DR3 ARI VOTable url=%s nbytes=%s", url, len(payload))
    return payload
