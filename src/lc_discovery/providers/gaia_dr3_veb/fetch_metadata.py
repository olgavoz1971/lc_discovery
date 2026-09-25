"""Provider-specific metadata enrichment for Gaia DR3 VEB fetched lightcurves."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET

from lc_discovery.providers.gaia_dr3_veb import config
from skvo_veb.utils.my_tools import PipeException

logger = logging.getLogger(__name__)

_VOTABLE_NS = "http://www.ivoa.net/xml/VOTable/v1.3"


def _local(tag: str) -> str:
    """Returns an XML tag without its namespace.

    Args:
        tag (str): Element tag.

    Returns:
        str: Local name.
    """
    return tag.rsplit("}", 1)[-1]


def _param(parent: ET.Element, name: str) -> ET.Element | None:
    """Finds a direct child PARAM by name.

    Args:
        parent (xml.etree.ElementTree.Element): Parent element.
        name (str): PARAM ``name``.

    Returns:
        xml.etree.ElementTree.Element or None: Matching PARAM.
    """
    for child in list(parent):
        if _local(child.tag) == "PARAM" and child.get("name") == name:
            return child
    return None


def _ensure_param(parent: ET.Element, name: str, value: str) -> None:
    """Sets a char PARAM on a parent, adding it when absent.

    Args:
        parent (xml.etree.ElementTree.Element): Parent element.
        name (str): PARAM ``name``.
        value (str): PARAM ``value``.
    """
    found = _param(parent, name)
    if found is None:
        tag = f"{{{_VOTABLE_NS}}}PARAM" if parent.tag.startswith("{") else "PARAM"
        found = ET.Element(tag)
        found.set("name", name)
        found.set("datatype", "char")
        found.set("arraysize", "*")
        parent.insert(0, found)
    found.set("value", value)


def enrich_votable(payload: bytes) -> bytes:
    """Applies the documented Gaia DR3 VEB corrections to a VOTable.

    The archive table name, description, and column names are kept. The
    flux zero point and its unit are replaced for the three Gaia filters.
    Facility and instrument are set to ``Gaia``.

    Args:
        payload (bytes): Downloaded ``accref`` VOTable.

    Returns:
        bytes: Enriched VOTable.

    Raises:
        PipeException: When the document has no TABLE description, or is not XML.
    """
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise PipeException(f"{config.DISPLAY_NAME}: downloaded accref is not XML: {exc}") from exc

    tables = [element for element in root.iter() if _local(element.tag) == "TABLE"]
    if not tables:
        raise PipeException(f"{config.DISPLAY_NAME}: retrieved lightcurve has no TABLE.")
    table = tables[0]
    description = ""
    for child in list(table):
        if _local(child.tag) == "DESCRIPTION" and child.text:
            description = child.text.strip()
            break
    if not description:
        raise PipeException(
            f"{config.DISPLAY_NAME}: retrieved lightcurve is missing TABLE description metadata."
        )

    _ensure_param(table, "facility_name", config.FACILITY_NAME)
    _ensure_param(table, "instrument_name", config.INSTRUMENT_NAME)

    for group in root.iter():
        if _local(group.tag) != "GROUP" or group.get("name") != "photcal":
            continue
        filter_param = _param(group, "filterIdentifier")
        if filter_param is None:
            continue
        filter_id = str(filter_param.get("value") or "").strip()
        if filter_id not in config.GAIA_DR3_ZP_MAG_BY_FILTER_IDENTIFIER:
            continue
        flux = _param(group, "zeroPointFlux")
        if flux is None:
            tag = f"{{{_VOTABLE_NS}}}PARAM" if group.tag.startswith("{") else "PARAM"
            flux = ET.SubElement(group, tag)
            flux.set("name", "zeroPointFlux")
            flux.set("datatype", "double")
        flux.set("value", str(config.GAIA_DR3_ZP_FLUX))
        flux.set("unit", config.GAIA_DR3_ZP_FLUX_UNIT)
        mag = _param(group, "zeroPointReferenceMagnitude")
        if mag is None:
            tag = f"{{{_VOTABLE_NS}}}PARAM" if group.tag.startswith("{") else "PARAM"
            mag = ET.SubElement(group, tag)
            mag.set("name", "zeroPointReferenceMagnitude")
            mag.set("datatype", "double")
        mag.set("value", str(config.GAIA_DR3_ZP_MAG_BY_FILTER_IDENTIFIER[filter_id]))
        mag.set("unit", config.GAIA_DR3_ZP_MAG_UNIT)
        mag.set("utype", "photDM:PhotCal.zeroPoint.referenceMagnitude.value")
        logger.info(
            "%s replaced zero points filter=%s zp_flux=%s %s zp_mag=%s %s (%s)",
            config.DISPLAY_NAME,
            filter_id,
            config.GAIA_DR3_ZP_FLUX,
            config.GAIA_DR3_ZP_FLUX_UNIT,
            config.GAIA_DR3_ZP_MAG_BY_FILTER_IDENTIFIER[filter_id],
            config.GAIA_DR3_ZP_MAG_UNIT,
            config.GAIA_DR3_ZP_SOURCE,
        )

    group_id = None
    for group in root.iter():
        if _local(group.tag) == "GROUP" and group.get("name") == "photcal" and group.get("ID"):
            group_id = group.get("ID")
            break
    if group_id:
        for field in table.iter():
            if _local(field.tag) != "FIELD":
                continue
            ucd = field.get("ucd") or ""
            if "stat.error" in ucd and not field.get("ref"):
                field.set("ref", group_id)

    epoch = _param(table, "epoch")
    if epoch is not None:
        epoch.set("ref", "ts")

    if root.tag.startswith("{"):
        ET.register_namespace("", _VOTABLE_NS)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)
