"""Fetch OGLE OCVS lightcurves from SSA ``accref`` product URLs."""

from __future__ import annotations

import logging
import urllib.error
import urllib.request

from lc_discovery.providers.ogle_ocvs import config

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_SEC = 120


def fetch_votable_bytes(
    accref: str,
    *,
    timeout_sec: float = _DEFAULT_TIMEOUT_SEC,
) -> bytes:
    """Downloads one lightcurve VOTable from an SSA ``accref`` URL.

    Args:
        accref (str): Absolute HTTP(S) URL to the lightcurve product.
        timeout_sec (float): Network read timeout in seconds.

    Returns:
        bytes: Archive VOTable, before enrichment.

    Raises:
        ValueError: When the URL is missing or the download fails.
    """
    url = str(accref or "").strip()
    if not url:
        raise ValueError("Lightcurve accref URL is empty.")

    try:
        request = urllib.request.Request(url, headers={"User-Agent": "lc_discovery"})
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            payload = response.read()
    except urllib.error.URLError as exc:
        logger.warning("%s accref download failed url=%s: %s", config.DISPLAY_NAME, url, exc)
        raise ValueError(f"Failed to download lightcurve from accref: {exc}") from exc

    logger.info(
        "%s fetched lightcurve VOTable from accref url=%s nbytes=%s",
        config.DISPLAY_NAME,
        url,
        len(payload),
    )
    return payload
