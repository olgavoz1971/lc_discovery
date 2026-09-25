"""Disk cache for Gaia DR3 (AIP) epoch photometry fetched on lightcurve load."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from lc_discovery.providers.gaia_dr3_aip import config

logger = logging.getLogger(__name__)

_STORE_LOCK = threading.Lock()


def _cache_dir() -> Path:
    """Returns the configured prefetch cache directory, creating it when needed.

    Returns:
        pathlib.Path: Writable cache directory path.
    """
    cache_dir = config.PREFETCH_CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _cache_path(source_id: int | str) -> Path:
    """Builds the on-disk path for one prefetched source record.

    Args:
        source_id (int or str): Gaia DR3 source identifier.

    Returns:
        pathlib.Path: JSON cache file path.
    """
    return _cache_dir() / f"{int(source_id)}.json"


def store_epoch_photometry(source_id: int | str, payload: dict[str, Any]) -> None:
    """Persists one prefetched epoch-photometry record keyed by ``source_id``.

    Args:
        source_id (int or str): Gaia DR3 source identifier.
        payload (dict): Serialisable epoch-photometry arrays and metadata.
    """
    path = _cache_path(source_id)
    document = {"source_id": int(source_id), **payload}
    with _STORE_LOCK:
        path.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
    logger.debug("%s prefetch stored source_id=%s path=%s", config.DISPLAY_NAME, source_id, path)


def epoch_photometry_is_cached(source_id: int | str) -> bool:
    """Reports whether epoch photometry for a source is present in the prefetch cache.

    Args:
        source_id (int or str): Gaia DR3 source identifier.

    Returns:
        bool: True when a cache file exists for the source.
    """
    return _cache_path(source_id).is_file()


def load_epoch_photometry(source_id: int | str) -> dict[str, Any]:
    """Loads one prefetched epoch-photometry record from disk.

    Args:
        source_id (int or str): Gaia DR3 source identifier.

    Returns:
        dict: Cached epoch-photometry payload.

    Raises:
        ValueError: When no prefetched record exists for the source.
    """
    path = _cache_path(source_id)
    if not path.is_file():
        raise ValueError(
            f"{config.DISPLAY_NAME}: no cached epoch photometry for source_id {source_id}."
        )
    with _STORE_LOCK:
        document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(
            f"{config.DISPLAY_NAME}: corrupt prefetch cache for source_id {source_id}."
        )
    return document


def clear_epoch_photometry(source_id: int | str) -> None:
    """Removes one prefetched epoch-photometry record, if present.

    Args:
        source_id (int or str): Gaia DR3 source identifier.
    """
    path = _cache_path(source_id)
    with _STORE_LOCK:
        if path.is_file():
            path.unlink()
