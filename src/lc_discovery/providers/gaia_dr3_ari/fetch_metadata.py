"""Provider-specific metadata enrichment for Gaia DR3 (ARI) fetched lightcurves."""

from __future__ import annotations

import copy
import io
import logging
import xml.etree.ElementTree as ET

from astropy.io.votable import parse as parse_votable

from lc_discovery.providers.gaia_dr3_ari import config

logger = logging.getLogger(__name__)

_DROPPED_COLUMNS = ("band", "source_id", "pf")
_UT_MAG = "photDM:PhotCal.zeroPoint.referenceMagnitude.value"


def _local(tag: str) -> str:
    """Returns an XML tag without its namespace.

    Args:
        tag (str): Element tag.

    Returns:
        str: Local name.
    """
    return tag.rsplit("}", 1)[-1]


def _children(parent: ET.Element, local: str) -> list[ET.Element]:
    """Returns direct children with a local name.

    Args:
        parent (xml.etree.ElementTree.Element): Parent element.
        local (str): Local tag name.

    Returns:
        list[xml.etree.ElementTree.Element]: Matching children.
    """
    return [child for child in list(parent) if _local(child.tag) == local]


def _param(parent: ET.Element, name: str) -> ET.Element | None:
    """Finds a direct child PARAM by name.

    Args:
        parent (xml.etree.ElementTree.Element): Parent element.
        name (str): PARAM ``name``.

    Returns:
        xml.etree.ElementTree.Element or None: Matching PARAM.
    """
    for child in _children(parent, "PARAM"):
        if child.get("name") == name:
            return child
    return None


def _field(table: ET.Element, name: str) -> ET.Element | None:
    """Finds a FIELD in a TABLE by name.

    Args:
        table (xml.etree.ElementTree.Element): TABLE element.
        name (str): FIELD ``name``.

    Returns:
        xml.etree.ElementTree.Element or None: Matching FIELD.
    """
    for child in _children(table, "FIELD"):
        if child.get("name") == name:
            return child
    return None


def _selected_data(payload: bytes, table_id: int) -> ET.Element:
    """Rewrites one table's DATA element without the dropped columns.

    Args:
        payload (bytes): Downloaded multi-table VOTable.
        table_id (int): Zero-based table index.

    Returns:
        xml.etree.ElementTree.Element: DATA element for the kept columns.

    Raises:
        ValueError: When ``table_id`` is out of range or the rewrite has no DATA.
    """
    votable = parse_votable(io.BytesIO(payload))
    tables = list(votable.iter_tables())
    if table_id < 0 or table_id >= len(tables):
        raise ValueError(
            f"{config.DISPLAY_NAME}: table_id {table_id} is outside the downloaded VOTable."
        )
    table = tables[table_id]
    names = table.array.dtype.names
    missing = [name for name in _DROPPED_COLUMNS if name not in names]
    if missing:
        raise ValueError(
            f"{config.DISPLAY_NAME}: retrieved lightcurve is missing columns {missing}."
        )
    keep = [name for name in names if name not in _DROPPED_COLUMNS]
    table.array = table.array[keep]
    for field in list(table.fields):
        if field.name in _DROPPED_COLUMNS:
            table.fields.remove(field)
    written = io.BytesIO()
    votable.to_xml(written)
    root = ET.fromstring(written.getvalue())
    written_tables = [element for element in root.iter() if _local(element.tag) == "TABLE"]
    for child in list(written_tables[table_id]):
        if _local(child.tag) == "DATA":
            return child
    raise ValueError(f"{config.DISPLAY_NAME}: selected table has no DATA element.")


def enrich_votable(payload: bytes, *, table_id: int) -> bytes:
    """Issues one Gaia DR3 ARI band as a calibrated VOTable.

    Other band tables are removed. Columns ``band``, ``source_id``, and ``pf``
    are removed because those values already live in table parameters. ``pf``
    is copied to a ``period`` parameter first. The magnitude photcal keeps the
    published Jy flux zero point and gains a magnitude zero point of 0 mag.
    Flux and its error use a separate photcal with flux zero point 1 in the
    flux column's unit.

    Args:
        payload (bytes): Downloaded multi-table VOTable.
        table_id (int): Catalogue table index (G=0, BP=1, RP=2).

    Returns:
        bytes: Single-band enriched VOTable.

    Raises:
        ValueError: When the document, the selected table, or its photcal is incomplete.
    """
    data = _selected_data(payload, int(table_id))
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ValueError(f"{config.DISPLAY_NAME}: downloaded product is not XML: {exc}") from exc

    tables = [element for element in root.iter() if _local(element.tag) == "TABLE"]
    if int(table_id) < 0 or int(table_id) >= len(tables):
        raise ValueError(
            f"{config.DISPLAY_NAME}: table_id {table_id} is outside the downloaded VOTable."
        )
    table = tables[int(table_id)]
    for other in tables:
        if other is not table:
            parent = _parent(root, other)
            if parent is not None:
                parent.remove(other)

    description = ""
    for child in _children(table, "DESCRIPTION"):
        if child.text and child.text.strip():
            description = child.text.strip()
            break
    if not description:
        raise ValueError(
            f"{config.DISPLAY_NAME}: retrieved lightcurve is missing TABLE description metadata."
        )

    pf = _param(table, "pf")
    if pf is None or pf.get("value") in (None, ""):
        raise ValueError(f"{config.DISPLAY_NAME}: TABLE PARAM pf is missing.")
    period = _param(table, "period")
    if period is None:
        period = ET.Element(pf.tag)
        period.set("name", "period")
        period.set("datatype", "double")
        period.set("unit", pf.get("unit") or "d")
        table.insert(list(table).index(pf) + 1, period)
    period.set("value", pf.get("value"))

    for name in _DROPPED_COLUMNS:
        field = _field(table, name)
        if field is None:
            raise ValueError(f"{config.DISPLAY_NAME}: retrieved lightcurve is missing column {name}.")
        table.remove(field)

    replaced = False
    for child in list(table):
        if _local(child.tag) == "DATA":
            table.remove(child)
            table.append(data)
            replaced = True
            break
    if not replaced:
        raise ValueError(f"{config.DISPLAY_NAME}: selected table has no DATA element.")

    mag = _field(table, "mag")
    flux = _field(table, "flux")
    flux_error = _field(table, "flux_error")
    if mag is None or flux is None or flux_error is None:
        raise ValueError(
            f"{config.DISPLAY_NAME}: retrieved lightcurve is missing mag, flux, or flux_error."
        )
    flux_unit = flux.get("unit")
    if not flux_unit:
        raise ValueError(f"{config.DISPLAY_NAME}: flux column has no unit.")
    group_id = mag.get("ref")
    if not group_id:
        raise ValueError(f"{config.DISPLAY_NAME}: mag column does not reference a photcal.")

    groups = [
        element
        for element in root.iter()
        if _local(element.tag) == "GROUP" and element.get("name") == "photcal"
    ]
    mag_group = next((group for group in groups if group.get("ID") == group_id), None)
    if mag_group is None:
        raise ValueError(f"{config.DISPLAY_NAME}: photcal group {group_id} is missing.")
    filter_param = _param(mag_group, "filterIdentifier")
    filter_id = str(filter_param.get("value") or "").strip() if filter_param is not None else ""
    if filter_id not in config.GAIA_ARI_ZP_MAG_FOR_FLUX_BY_FILTER_IDENTIFIER:
        raise ValueError(
            f"{config.DISPLAY_NAME}: no flux magnitude zero point for filter {filter_id!r}."
        )

    if _param(mag_group, "zeroPointReferenceMagnitude") is None:
        mag_zp = ET.SubElement(mag_group, _param_tag(mag_group))
        mag_zp.set("name", "zeroPointReferenceMagnitude")
        mag_zp.set("datatype", "double")
        mag_zp.set("unit", config.GAIA_ARI_ZP_MAG_UNIT)
        mag_zp.set("utype", _UT_MAG)
        mag_zp.set("value", str(config.GAIA_ARI_ZERO_POINT_REFERENCE_MAGNITUDE))

    flux_group = copy.deepcopy(mag_group)
    flux_group_id = f"{group_id}-flux"
    flux_group.set("ID", flux_group_id)
    flux_zp = _param(flux_group, "zeroPointFlux")
    if flux_zp is None:
        raise ValueError(f"{config.DISPLAY_NAME}: zeroPointFlux is missing from the photcal group.")
    flux_zp.set("value", str(config.GAIA_ARI_ZP_FLUX))
    flux_zp.set("unit", flux_unit)
    flux_mag = _param(flux_group, "zeroPointReferenceMagnitude")
    flux_mag.set("value", str(config.GAIA_ARI_ZP_MAG_FOR_FLUX_BY_FILTER_IDENTIFIER[filter_id]))
    parent = _parent(root, mag_group)
    parent.insert(list(parent).index(mag_group) + 1, flux_group)
    flux.set("ref", flux_group_id)
    flux_error.set("ref", flux_group_id)

    for group in groups:
        if group.get("ID") != group_id:
            owner = _parent(root, group)
            if owner is not None:
                owner.remove(group)

    logger.info(
        "%s issued table_id=%s filter=%s zp_mag=%s zp_flux=%s %s (%s)",
        config.DISPLAY_NAME,
        table_id,
        filter_id,
        config.GAIA_ARI_ZERO_POINT_REFERENCE_MAGNITUDE,
        config.GAIA_ARI_ZP_FLUX,
        flux_unit,
        config.GAIA_ARI_ZP_SOURCE,
    )
    ET.register_namespace("", "http://www.ivoa.net/xml/VOTable/v1.3")
    ET.register_namespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")
    ET.register_namespace("stc", "http://www.ivoa.net/xml/STC/v1.30")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _param_tag(group: ET.Element) -> str:
    """Returns a PARAM tag matching an existing child namespace.

    Args:
        group (xml.etree.ElementTree.Element): Photcal GROUP.

    Returns:
        str: PARAM tag.
    """
    for child in list(group):
        if _local(child.tag) == "PARAM":
            return child.tag
    return "PARAM"


def _parent(root: ET.Element, node: ET.Element) -> ET.Element | None:
    """Returns the parent of a node.

    Args:
        root (xml.etree.ElementTree.Element): Document root.
        node (xml.etree.ElementTree.Element): Child to locate.

    Returns:
        xml.etree.ElementTree.Element or None: Parent element.
    """
    for parent in root.iter():
        if node in list(parent):
            return parent
    return None
