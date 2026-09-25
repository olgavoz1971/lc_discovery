"""Download ZTF epoch photometry via ``ztfquery``."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd
import requests

from lc_discovery.providers.ztf import config

logger = logging.getLogger(__name__)


def fetch_photometry_by_oid(
    oid: int | str,
    *,
    fetch_quality: str = config.FETCH_QUALITY_RAW,
) -> pd.DataFrame:
    """Downloads epoch photometry for one ZTF OID.

    Args:
        oid (int or str): ZTF object/lightcurve identifier.
        fetch_quality (str): ``raw`` or ``bad_catflags`` (see provider config).

    Returns:
        pandas.DataFrame: Epoch table from ``ztfquery``.

    Raises:
        ValueError: When download fails or returns no rows.
    """
    oid_int = int(oid)
    quality = str(fetch_quality or config.FETCH_QUALITY_RAW).strip().lower()
    if quality not in (config.FETCH_QUALITY_RAW, config.FETCH_QUALITY_BAD_CATFLAGS):
        raise ValueError(
            f"{config.DISPLAY_NAME}: unsupported fetch_quality {fetch_quality!r}. "
            f"Use {config.FETCH_QUALITY_RAW!r} or {config.FETCH_QUALITY_BAD_CATFLAGS!r}."
        )
    try:
        from ztfquery import lightcurve
    except ImportError as exc:
        raise ValueError(
            f"{config.DISPLAY_NAME}: ztfquery is required but is not installed."
        ) from exc

    logger.info(
        "%s ztfquery fetch oid=%s quality=%s",
        config.DISPLAY_NAME,
        oid_int,
        quality,
    )
    try:
        url = lightcurve.build_url(ID=str(oid_int), FORMAT="votable")
        response = requests.get(url, cookies={}, timeout=120)
        response.raise_for_status()
        frame = _frame_from_irsa_votable(response.content)
    except Exception as exc:
        raise ValueError(
            f"{config.DISPLAY_NAME}: lightcurve download failed for oid={oid_int}: {exc}"
        ) from exc

    if frame is None or len(frame) == 0:
        raise ValueError(
            f"{config.DISPLAY_NAME}: no epoch photometry returned for oid={oid_int}."
        )

    if quality == config.FETCH_QUALITY_BAD_CATFLAGS:
        frame = _apply_bad_catflags_mask(frame)

    if frame is None or len(frame) == 0:
        raise ValueError(
            f"{config.DISPLAY_NAME}: no epochs remain after quality filtering "
            f"for oid={oid_int} (quality={quality!r})."
        )
    return frame


def _local(tag: str) -> str:
    """Returns an XML tag without its namespace.

    Args:
        tag (str): Element tag.

    Returns:
        str: Local name.
    """
    return tag.rsplit("}", 1)[-1]


def _frame_from_irsa_votable(payload: bytes) -> pd.DataFrame:
    """Reads an IRSA light-curve VOTable into a table plus its FIELD metadata.

    UCD, unit, datatype, and description are taken from each FIELD and stored
    on ``frame.attrs['irsa_fields']``.

    Args:
        payload (bytes): IRSA ``FORMAT=votable`` response.

    Returns:
        pandas.DataFrame: One row per epoch.

    Raises:
        ValueError: When the document is not a TABLEDATA VOTable.
    """
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ValueError(f"{config.DISPLAY_NAME}: IRSA lightcurve is not XML: {exc}") from exc
    tables = [element for element in root.iter() if _local(element.tag) == "TABLE"]
    if not tables:
        raise ValueError(f"{config.DISPLAY_NAME}: IRSA lightcurve VOTable has no TABLE.")
    table = tables[0]
    fields = [element for element in list(table) if _local(element.tag) == "FIELD"]
    if not fields:
        raise ValueError(f"{config.DISPLAY_NAME}: IRSA lightcurve VOTable has no FIELD.")
    meta: dict[str, dict[str, str]] = {}
    names: list[str] = []
    for field in fields:
        name = field.get("name")
        if not name:
            raise ValueError(f"{config.DISPLAY_NAME}: IRSA lightcurve FIELD has no name.")
        names.append(name)
        entry: dict[str, str] = {}
        for key in ("ucd", "unit", "datatype"):
            value = field.get(key)
            if value:
                entry[key] = value
        for child in list(field):
            if _local(child.tag) == "DESCRIPTION" and child.text and child.text.strip():
                entry["description"] = child.text.strip()
        meta[name] = entry
    data_nodes = [element for element in table.iter() if _local(element.tag) == "TABLEDATA"]
    if not data_nodes:
        raise ValueError(f"{config.DISPLAY_NAME}: IRSA lightcurve VOTable is not TABLEDATA.")
    rows: list[list[str]] = []
    for tr in data_nodes[0]:
        if _local(tr.tag) != "TR":
            continue
        cells = [child.text or "" for child in list(tr) if _local(child.tag) == "TD"]
        if len(cells) != len(names):
            raise ValueError(f"{config.DISPLAY_NAME}: IRSA lightcurve row does not match its fields.")
        rows.append(cells)
    frame = pd.DataFrame(rows, columns=names)
    frame.attrs["irsa_fields"] = meta
    return frame


def _apply_bad_catflags_mask(frame: pd.DataFrame) -> pd.DataFrame:
    """Removes epochs flagged by ZTF ``catflags`` bit 15 (cloud/moon).

    Args:
        frame (pandas.DataFrame): Raw ``ztfquery`` epoch table.

    Returns:
        pandas.DataFrame: Filtered copy.

    Raises:
        ValueError: When ``catflags`` is missing from the table.
    """
    if "catflags" not in frame.columns:
        raise ValueError(
            f"{config.DISPLAY_NAME}: catflags column missing; cannot apply "
            f"{config.FETCH_QUALITY_BAD_CATFLAGS!r} filtering."
        )
    mask = config.ZTF_BAD_CATFLAGS_MASK
    flags = np.asarray(frame["catflags"], dtype=np.int64)
    keep = (flags & mask) == 0
    filtered = frame.loc[keep].copy()
    logger.info(
        "%s bad_catflags filter kept %s/%s epochs (mask=%s)",
        config.DISPLAY_NAME,
        len(filtered),
        len(frame),
        mask,
    )
    return filtered
