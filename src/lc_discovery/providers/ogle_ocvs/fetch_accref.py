"""Fetch OGLE OCVS lightcurves from SSA ``accref`` product URLs."""

from __future__ import annotations

import io
import logging
import urllib.error
import urllib.request

from lc_discovery.providers.ogle_ocvs import config
from skvo_veb.utils.my_tools import PipeException
from volightcurve import VOLightCurve

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
        PipeException: When the URL is missing or the download fails.
    """
    url = str(accref or "").strip()
    if not url:
        raise PipeException("Lightcurve accref URL is empty.")

    try:
        request = urllib.request.Request(url, headers={"User-Agent": "lc_discovery"})
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            payload = response.read()
    except urllib.error.URLError as exc:
        logger.warning("%s accref download failed url=%s: %s", config.DISPLAY_NAME, url, exc)
        raise PipeException(f"Failed to download lightcurve from accref: {exc}") from exc

    logger.info(
        "%s fetched lightcurve VOTable from accref url=%s nbytes=%s",
        config.DISPLAY_NAME,
        url,
        len(payload),
    )
    return payload


def fetch_volightcurve_from_accref(
    accref: str,
    *,
    timeout_sec: float = _DEFAULT_TIMEOUT_SEC,
    provider_label: str | None = None,
) -> VOLightCurve:
    """Downloads one lightcurve and parses it for providers that still return VOLightCurve.

    Args:
        accref (str): Absolute HTTP(S) URL to the lightcurve product.
        timeout_sec (float): Network read timeout in seconds.
        provider_label (str, optional): Mission display name for log messages.

    Returns:
        VOLightCurve: Parsed lightcurve.

    Raises:
        PipeException: When the URL is missing or the download/parse fails.
    """
    url = str(accref or "").strip()
    label = provider_label or config.DISPLAY_NAME
    payload = fetch_votable_bytes(accref, timeout_sec=timeout_sec)
    try:
        volc = VOLightCurve(io.BytesIO(payload))
    except Exception as exc:
        logger.warning("%s accref VOTable parse failed url=%s: %s", label, url, exc)
        raise PipeException(f"Downloaded accref is not a valid lightcurve: {exc}") from exc

    logger.info("%s fetched lightcurve from accref url=%s n_points=%s", label, url, len(volc))
    return volc
