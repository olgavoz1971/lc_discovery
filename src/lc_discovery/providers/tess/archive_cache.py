"""Shared Lightkurve cache for TESS archive light-curve FITS files.

Owns everything about obtaining a readable FITS from the cache: the expected
path, the MAST download on a miss, honest failure classification, a single
purge-and-retry for a truncated file, and opening the product. The host
never repeats this logic.
"""

from __future__ import annotations

import logging
import os
from typing import Literal

from lc_discovery.providers.tess import config

logger = logging.getLogger(__name__)

FAILURE_TRUNCATED = "truncated_cache"
FAILURE_UNSUPPORTED = "unsupported_product"
FAILURE_OTHER = "other"
FailureKind = Literal["truncated_cache", "unsupported_product", "other"]

_CANNED_CORRUPT_DOWNLOAD = "this file may be corrupt due to an interrupted download"
_TRUNCATED_MARKERS = (
    "buffer is too small for requested array",
    "file is truncated",
    "header missing end card",
    "incomplete or truncated",
)
_UNSUPPORTED_READER_MARKERS = (
    "unexpected keyword argument",
    "quality_bitmask",
    "not a recognised tess pipeline",
)


def cache_dir() -> str:
    """Returns the active Lightkurve download cache directory.

    Returns:
        str: Directory path (``lightkurve.config.get_cache_dir()``).
    """
    from lightkurve.config import get_cache_dir

    return get_cache_dir()


def _exception_chain_text(exc: BaseException) -> str:
    """Joins type names and messages from an exception and its cause chain.

    Args:
        exc (BaseException): Outermost exception.

    Returns:
        str: Lower-cased diagnostic text.
    """
    parts: list[str] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        parts.append(f"{type(current).__name__}: {current}")
        current = current.__cause__ or current.__context__
    return "\n".join(parts).lower()


def classify_failure(exc: BaseException) -> FailureKind:
    """Classifies a read failure for the purge policy.

    Lightkurve appends a canned "interrupted download" sentence to almost
    every ``read()`` error, so that text is ignored. A truncated FITS is
    recognised from the cause chain.

    Args:
        exc (BaseException): Exception raised while reading the product.

    Returns:
        str: ``truncated_cache``, ``unsupported_product``, or ``other``.
    """
    text = _exception_chain_text(exc)
    if any(marker in text for marker in _TRUNCATED_MARKERS):
        return FAILURE_TRUNCATED
    if any(marker in text for marker in _UNSUPPORTED_READER_MARKERS):
        return FAILURE_UNSUPPORTED
    if "of type generic" in text and "typeerror" in text:
        return FAILURE_UNSUPPORTED
    return FAILURE_OTHER


def _strip_canned_sentence(message: str) -> str:
    """Removes Lightkurve's canned corrupt-download paragraph.

    Args:
        message (str): Raw exception text.

    Returns:
        str: Remaining text, stripped.
    """
    index = message.lower().find(_CANNED_CORRUPT_DOWNLOAD)
    return (message if index == -1 else message[:index]).strip()


def format_failure(exc: BaseException, *, author: str) -> str:
    """Builds a user-facing message without a false "corrupt file" claim.

    Args:
        exc (BaseException): Failure raised while reading.
        author (str): Pipeline author tag.

    Returns:
        str: British English message.
    """
    kind = classify_failure(exc)
    if kind == FAILURE_TRUNCATED:
        return (
            f"{config.DISPLAY_NAME}: the cached FITS file for author {author} "
            "appears incomplete or truncated."
        )
    if kind == FAILURE_UNSUPPORTED:
        return (
            f"{config.DISPLAY_NAME}: this archive product (author {author}) is not "
            "a recognised TESS pipeline light curve and cannot be opened. The "
            "cached file was left unchanged."
        )
    inner = exc.__cause__ if isinstance(exc.__cause__, BaseException) else exc
    cleaned = _strip_canned_sentence(str(inner)) or _strip_canned_sentence(str(exc))
    return f"{config.DISPLAY_NAME}: {cleaned or 'unknown Lightkurve error'}"


def product_pointer(search_result) -> dict[str, str]:
    """Builds the pointer to the MAST pipeline FITS of a one-row search result.

    Args:
        search_result: One-row Lightkurve ``SearchResult``.

    Returns:
        dict[str, str]: ``obs_collection``, ``obs_id``, ``product_filename``.
    """
    row = search_result.table[0]
    return {
        "obs_collection": str(row["obs_collection"]),
        "obs_id": str(row["obs_id"]),
        "product_filename": str(row["productFilename"]),
    }


def pointer_path(pointer: dict[str, str]) -> str:
    """Resolves a pointer against the shared Lightkurve cache.

    Args:
        pointer (dict[str, str]): Pointer from ``product_pointer``.

    Returns:
        str: Absolute path under ``mastDownload``.
    """
    return os.path.join(
        cache_dir().rstrip("/"),
        "mastDownload",
        pointer["obs_collection"],
        pointer["obs_id"],
        pointer["product_filename"],
    )


def ensure_fits(search_result) -> str:
    """Returns the local FITS path, downloading from MAST on a cache miss.

    Args:
        search_result: One-row Lightkurve ``SearchResult``.

    Returns:
        str: Path to the product FITS.

    Raises:
        ValueError: When MAST does not complete the download.
    """
    path = pointer_path(product_pointer(search_result))
    if os.path.isfile(path):
        logger.info("%s cache hit path=%s", config.DISPLAY_NAME, path)
        return path
    from astroquery.mast import Observations

    logger.info("%s cache miss; fetching from MAST path=%s", config.DISPLAY_NAME, path)
    response = Observations.download_products(
        search_result.table[:1], mrp_only=False, download_dir=cache_dir()
    )[0]
    if response["Status"] != "COMPLETE":
        raise ValueError(
            f"{config.DISPLAY_NAME}: MAST download {response['Status']}: "
            f"{response['Message']}."
        )
    return str(response["Local Path"])


def purge(pointer: dict[str, str]) -> bool:
    """Deletes one cached FITS file.

    Args:
        pointer (dict[str, str]): Pointer from ``product_pointer``.

    Returns:
        bool: True when a file was deleted, False when none was cached.

    Raises:
        ValueError: When the file exists but cannot be deleted.
    """
    path = pointer_path(pointer)
    if not os.path.isfile(path):
        return False
    try:
        os.remove(path)
    except OSError as exc:
        raise ValueError(
            f"{config.DISPLAY_NAME}: cannot delete cached file {path}: {exc}"
        ) from exc
    logger.info("%s purged cached FITS path=%s", config.DISPLAY_NAME, path)
    return True


def _first_table_columns(path: str) -> set[str]:
    """Returns lower-case column names of the first table HDU.

    Args:
        path (str): FITS path.

    Returns:
        set[str]: Column names, empty when no table HDU exists.
    """
    from astropy.io import fits

    with fits.open(path) as hdulist:
        for hdu in hdulist[1:]:
            names = getattr(getattr(hdu, "columns", None), "names", None)
            if names:
                return {str(name).lower() for name in names}
    return set()


def open_product(path: str):
    """Opens a cached FITS light curve.

    Typed Kepler/TESS products use ``quality_bitmask='default'``. Generic
    HLSPs (TARS) are opened without that keyword, and only when the first
    table has ``TIME`` and ``FLUX``.

    Args:
        path (str): FITS path.

    Returns:
        lightkurve.LightCurve: Opened product.

    Raises:
        ValueError: When the file is a generic product without TIME and FLUX.
    """
    from astropy.io import fits
    from lightkurve.io.detect import detect_filetype
    from lightkurve.io.read import read

    with fits.open(path) as hdulist:
        kind = detect_filetype(hdulist)
    if kind in (None, "generic"):
        names = _first_table_columns(path)
        if "time" not in names or "flux" not in names:
            raise ValueError("not a recognised tess pipeline light curve")
        logger.info("%s opening generic FITS without quality_bitmask path=%s", config.DISPLAY_NAME, path)
        return read(path)
    return read(path, quality_bitmask="default")


def attach_author(lc, author: str) -> None:
    """Copies the search-table author onto the Lightkurve object when missing.

    Args:
        lc: Lightkurve light curve.
        author (str): Author from the one-row search result.
    """
    meta = getattr(lc, "meta", None)
    if isinstance(meta, dict) and not meta.get("AUTHOR"):
        meta["AUTHOR"] = author


def read_with_repair(search_result, *, author: str):
    """Reads the product, repairing a truncated cached file once.

    Args:
        search_result: One-row Lightkurve ``SearchResult``.
        author (str): Pipeline author tag (for messages).

    Returns:
        tuple: ``(lightkurve light curve, pointer dict)``.

    Raises:
        ValueError: With an honest message when the product cannot be read.
    """
    pointer = product_pointer(search_result)
    path = ensure_fits(search_result)
    try:
        lc = open_product(path)
    except Exception as exc:
        if classify_failure(exc) != FAILURE_TRUNCATED:
            raise ValueError(format_failure(exc, author=author)) from exc
        logger.warning("%s cached FITS truncated; purging and retrying once.", config.DISPLAY_NAME)
        purge(pointer)
        path = ensure_fits(search_result)
        try:
            lc = open_product(path)
        except Exception as retry_exc:
            raise ValueError(format_failure(retry_exc, author=author)) from retry_exc
    attach_author(lc, author)
    return lc, pointer
