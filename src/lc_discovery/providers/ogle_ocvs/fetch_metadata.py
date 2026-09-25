"""Provider-specific metadata enrichment for OGLE OCVS fetched lightcurves."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET

from lc_discovery.providers.ogle_ocvs import config
from skvo_veb.utils.my_tools import PipeException

logger = logging.getLogger(__name__)

_VOTABLE_NS = "http://www.ivoa.net/xml/VOTable/v1.3"
_UT_FILTER = "photDM:PhotometryFilter.identifier"
_UT_FLUX = "photDM:PhotCal.zeroPoint.flux.value"
_UT_MAG = "photDM:PhotCal.zeroPoint.referenceMagnitude.value"


def _local(tag: str) -> str:
    """Returns an XML tag without its namespace.

    Args:
        tag (str): Element tag.

    Returns:
        str: Local name.
    """
    return tag.rsplit("}", 1)[-1]


def _tag(parent: ET.Element, local: str) -> str:
    """Returns a child tag in the parent's namespace when the parent has one.

    Args:
        parent (xml.etree.ElementTree.Element): Parent element.
        local (str): Local name.

    Returns:
        str: Tag to pass to ElementTree.
    """
    if parent.tag.startswith("{"):
        return f"{{{_VOTABLE_NS}}}{local}"
    return local


def _index_by_id(root: ET.Element) -> dict[str, ET.Element]:
    """Maps every element ``ID`` in the document.

    Args:
        root (xml.etree.ElementTree.Element): VOTable root.

    Returns:
        dict[str, xml.etree.ElementTree.Element]: Elements keyed by ``ID``.
    """
    found: dict[str, ET.Element] = {}
    for element in root.iter():
        element_id = element.get("ID")
        if element_id:
            found[element_id] = element
    return found


def _resolved_param(child: ET.Element, by_id: dict[str, ET.Element]) -> ET.Element | None:
    """Returns a PARAM, following a PARAMref when that is what the child is.

    Args:
        child (xml.etree.ElementTree.Element): Direct child of a photcal GROUP.
        by_id (dict[str, xml.etree.ElementTree.Element]): Document ID index.

    Returns:
        xml.etree.ElementTree.Element or None: The PARAM element.
    """
    local = _local(child.tag)
    if local == "PARAM":
        return child
    if local == "PARAMref":
        target = by_id.get(child.get("ref") or "")
        if target is not None and _local(target.tag) == "PARAM":
            return target
    return None


def _utype(element: ET.Element) -> str:
    """Returns the utype attribute.

    Args:
        element (xml.etree.ElementTree.Element): PARAM or PARAMref.

    Returns:
        str: utype, or an empty string.
    """
    return element.get("utype") or ""


def _ensure_char_param(parent: ET.Element, name: str, value: str) -> None:
    """Sets a char PARAM, inserting it at the start of the parent when absent.

    Args:
        parent (xml.etree.ElementTree.Element): TABLE element.
        name (str): PARAM ``name``.
        value (str): PARAM ``value``.
    """
    found = None
    for child in list(parent):
        if _local(child.tag) == "PARAM" and child.get("name") == name:
            found = child
            break
    if found is None:
        found = ET.Element(_tag(parent, "PARAM"))
        found.set("name", name)
        found.set("datatype", "char")
        found.set("arraysize", "*")
        parent.insert(0, found)
    found.set("value", value)


def enrich_votable(payload: bytes) -> bytes:
    """Applies the documented OGLE OCVS corrections to a VOTable.

    The archive table name, description, column names, and flux zero point
    are kept. A missing magnitude zero point is set to 0 mag for the Bessell
    filter identifiers in this provider's config. Facility and instrument
    are set from that config.

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

    _ensure_char_param(table, "facility_name", config.FACILITY_NAME)
    _ensure_char_param(table, "instrument_name", config.INSTRUMENT_NAME)

    by_id = _index_by_id(root)
    photcal_groups: list[ET.Element] = []
    for group in root.iter():
        if _local(group.tag) != "GROUP" or group.get("name") != "photcal":
            continue
        photcal_groups.append(group)
        filter_id = ""
        has_mag = False
        for child in list(group):
            param = _resolved_param(child, by_id)
            if param is None:
                continue
            utype = _utype(child) or _utype(param)
            if utype == _UT_FILTER:
                filter_id = str(param.get("value") or "").strip()
            if utype == _UT_MAG:
                has_mag = True
        if filter_id not in config.ZP_MAG_BY_FILTER_IDENTIFIER or has_mag:
            if filter_id and filter_id not in config.ZP_MAG_BY_FILTER_IDENTIFIER:
                logger.info(
                    "%s left magnitude zero point unchanged filter=%s",
                    config.DISPLAY_NAME,
                    filter_id,
                )
            continue
        mag = ET.SubElement(group, _tag(group, "PARAM"))
        mag.set("name", "zeroPointReferenceMagnitude")
        mag.set("datatype", "double")
        mag.set("value", str(config.ZP_MAG_BY_FILTER_IDENTIFIER[filter_id]))
        mag.set("unit", config.ZP_MAG_UNIT)
        mag.set("utype", _UT_MAG)
        logger.info(
            "%s set magnitude zero point filter=%s zp_mag=%s %s",
            config.DISPLAY_NAME,
            filter_id,
            config.ZP_MAG_BY_FILTER_IDENTIFIER[filter_id],
            config.ZP_MAG_UNIT,
        )

    if len(photcal_groups) == 1:
        group = photcal_groups[0]
        group_id = group.get("ID")
        if not group_id:
            group_id = "photcal"
            group.set("ID", group_id)
        for field in table.iter():
            if _local(field.tag) != "FIELD":
                continue
            ucd = field.get("ucd") or ""
            if "stat.error" in ucd and not field.get("ref"):
                field.set("ref", group_id)

    for child in list(table):
        if _local(child.tag) == "PARAM" and child.get("name") == "epoch":
            child.set("ref", "ts")

    if root.tag.startswith("{"):
        ET.register_namespace("", _VOTABLE_NS)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)
