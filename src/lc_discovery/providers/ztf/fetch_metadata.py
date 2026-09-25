"""Lookup-aware metadata enrichment for fetched ZTF lightcurves."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd

from lc_discovery.discovery_fetch_context import (
    DiscoveryFetchContext,
    effective_lookup_association_arcsec as _shared_effective_lookup_association_arcsec,
    resolve_lookup_name_for_discovery_fetch,
)
from lc_discovery.providers.ztf import config
from lc_discovery.epoch import JD_TO_MJD

logger = logging.getLogger(__name__)

_NS = "http://www.ivoa.net/xml/VOTable/v1.3"
_UT_FILTER = "photDM:PhotometryFilter.identifier"
_UT_FLUX = "photDM:PhotCal.zeroPoint.flux.value"
_UT_MAG = "photDM:PhotCal.zeroPoint.referenceMagnitude.value"
_UT_SYS = "photDM:PhotCal.magnitudeSystem.type"
_UT_WAVE = "photDM:PhotometryFilter.spectralLocation.value"

# Source column, issued name. UCD, unit, datatype, and description come from
# the IRSA FIELD of the source column when the download carried them.
_COLUMNS = (
    ("hjd", "hjd"),
    ("hmjd", "hmjd"),
    ("mag", "mag"),
    ("magerr", "mag_err"),
    ("oid", "oid"),
    ("catflags", "catflag"),
    ("chi", "chi"),
    ("sharp", "sharp"),
    ("field", "field"),
    ("ccdid", "ccdid"),
    ("qid", "qid"),
    ("limitmag", "limitmag"),
)
_INTEGRAL_DATATYPES = {"long", "int", "short", "unsignedByte", "unsignedShort", "unsignedInt"}


def votable_from_epochs(
    frame: pd.DataFrame,
    *,
    filtercode: str,
    ra_deg: float | None,
    dec_deg: float | None,
) -> bytes:
    """Writes one ZTF light curve as a calibrated VOTable.

    Time is ``hjd`` when that column exists, otherwise ``hmjd``. A row is
    removed when time or magnitude is missing. A missing magnitude error stays
    an empty cell.

    Args:
        frame (pandas.DataFrame): Epoch table from ``ztfquery``.
        filtercode (str): IRSA filter code ``zg``, ``zr``, or ``zi``.
        ra_deg (float or None): Object right ascension in degrees.
        dec_deg (float or None): Object declination in degrees.

    Returns:
        bytes: Calibrated VOTable.

    Raises:
        ValueError: When required columns or usable rows are missing.
    """
    if frame is None or len(frame) == 0:
        raise ValueError(f"{config.DISPLAY_NAME}: empty epoch table.")
    if "hjd" in frame.columns:
        time_source = "hjd"
        timeorigin = 0.0
    elif "hmjd" in frame.columns:
        time_source = "hmjd"
        timeorigin = JD_TO_MJD
    else:
        raise ValueError(f"{config.DISPLAY_NAME}: epoch table must contain hjd or hmjd.")
    fields = frame.attrs.get("irsa_fields") or {}
    needed = [source for source, _out in _COLUMNS if source not in ("hjd", "hmjd")]
    missing = [name for name in needed if name not in frame.columns]
    if missing:
        raise ValueError(f"{config.DISPLAY_NAME}: epoch table missing columns {missing}.")

    band = config.band_spec_for_filtercode(filtercode)
    kept: list[list[str]] = []
    for _, row in frame.iterrows():
        time_text = _cell(row[time_source])
        mag_text = _cell(row["mag"])
        if time_text == "" or mag_text == "":
            continue
        values = []
        for source, _out in _COLUMNS:
            if source in ("hjd", "hmjd"):
                if source == time_source:
                    values.append(time_text)
                continue
            datatype = str((fields.get(source) or {}).get("datatype") or "")
            values.append(_cell(row[source], integral=datatype in _INTEGRAL_DATATYPES))
        kept.append(values)
    if not kept:
        raise ValueError(f"{config.DISPLAY_NAME}: no epochs with time and magnitude.")

    output_columns = [
        item for item in _COLUMNS if item[0] == time_source or item[0] not in ("hjd", "hmjd")
    ]
    wavelength_m = band.effective_wavelength_angstrom * 1e-10
    ET.register_namespace("", _NS)
    root = ET.Element(f"{{{_NS}}}VOTABLE", {"version": "1.3"})
    resource = ET.SubElement(root, f"{{{_NS}}}RESOURCE")
    timesys = ET.SubElement(resource, f"{{{_NS}}}TIMESYS")
    timesys.set("ID", "ts")
    timesys.set("refposition", config.ZTF_REFPOSITION)
    timesys.set("timescale", config.ZTF_TIMESCALE)
    timesys.set("timeorigin", str(timeorigin))
    group = ET.SubElement(resource, f"{{{_NS}}}GROUP")
    group.set("ID", "photcal")
    group.set("name", "photcal")
    _param(group, "filterIdentifier", band.filter_identifier, utype=_UT_FILTER, arraysize="*")
    _param(group, "zeroPointFlux", repr(float(band.zp_flux_jy)), utype=_UT_FLUX, unit="Jy", datatype="double")
    _param(group, "magnitudeSystem", band.mag_sys, utype=_UT_SYS, arraysize="*")
    _param(group, "effectiveWavelength", repr(float(wavelength_m)), utype=_UT_WAVE, unit="m", datatype="double")
    _param(group, "zeroPointReferenceMagnitude", "0.0", utype=_UT_MAG, unit="mag", datatype="double")
    for field_id in ("mag", "mag_err"):
        fieldref = ET.SubElement(group, f"{{{_NS}}}FIELDref")
        fieldref.set("ref", field_id)

    oid_text = _cell(frame["oid"].iloc[0], integral=True)
    table = ET.SubElement(resource, f"{{{_NS}}}TABLE")
    table.set("name", f"{config.format_ztf_oid_name(oid_text)} {band.filter_name}")
    if ra_deg is not None:
        _table_param(table, "ra", repr(float(ra_deg)), datatype="double", ucd="pos.eq.ra")
    if dec_deg is not None:
        _table_param(table, "dec", repr(float(dec_deg)), datatype="double", ucd="pos.eq.dec")
    for source, out_name in output_columns:
        remote = fields.get(source) or {}
        field_id = out_name if out_name in ("mag", "mag_err") or source == time_source else None
        ref = "ts" if source == time_source else ("photcal" if out_name in ("mag", "mag_err") else None)
        _field(
            table,
            out_name,
            str(remote.get("datatype") or "double"),
            ucd=remote.get("ucd") or None,
            unit=remote.get("unit") or None,
            ref=ref,
            field_id=field_id or out_name,
            description=remote.get("description") or None,
        )
    data = ET.SubElement(table, f"{{{_NS}}}DATA")
    tabledata = ET.SubElement(data, f"{{{_NS}}}TABLEDATA")
    for values in kept:
        tr = ET.SubElement(tabledata, f"{{{_NS}}}TR")
        for text in values:
            cell = ET.SubElement(tr, f"{{{_NS}}}TD")
            cell.text = text
    logger.info(
        "%s issued filter=%s n_rows=%s time=%s",
        config.DISPLAY_NAME,
        band.filtercode,
        len(kept),
        time_source,
    )
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _cell(value, *, integral: bool = False) -> str:
    """Formats one cell, leaving a missing value empty.

    Args:
        value: Epoch-table cell.

    Returns:
        str: Text for one TABLEDATA cell.
    """
    if value is None or (isinstance(value, float) and value != value):
        return ""
    if isinstance(value, np.ma.core.MaskedConstant) or np.ma.is_masked(value):
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, (float, np.floating, int, np.integer)):
        number = float(value)
        if number != number:
            return ""
        if integral:
            return str(int(number))
        return repr(number)
    return str(value).strip()


def _table_param(table, name, value, *, datatype="char", ucd=None) -> None:
    """Appends one TABLE PARAM.

    Args:
        table: TABLE element.
        name (str): PARAM name.
        value (str): PARAM value.
        datatype (str): VOTable datatype.
        ucd (str, optional): UCD.
    """
    param = ET.SubElement(table, f"{{{_NS}}}PARAM")
    param.set("name", name)
    param.set("datatype", datatype)
    param.set("value", value)
    if datatype == "char":
        param.set("arraysize", "*")
    if ucd:
        param.set("ucd", ucd)


def _param(parent, name, value, *, utype, unit=None, datatype="char", arraysize=None) -> None:
    """Appends one photcal PARAM.

    Args:
        parent: GROUP element.
        name (str): PARAM name.
        value (str): PARAM value.
        utype (str): PhotDM utype.
        unit (str, optional): Unit.
        datatype (str): VOTable datatype.
        arraysize (str, optional): Character arraysize.
    """
    param = ET.SubElement(parent, f"{{{_NS}}}PARAM")
    param.set("name", name)
    param.set("datatype", datatype)
    param.set("value", value)
    param.set("utype", utype)
    if unit:
        param.set("unit", unit)
    if arraysize:
        param.set("arraysize", arraysize)


def _field(table, name, datatype, *, ucd, unit=None, ref=None, field_id=None, description=None) -> None:
    """Appends one FIELD and its description.

    Args:
        table: TABLE element.
        name (str): Column name.
        datatype (str): VOTable datatype.
        ucd (str): Column UCD.
        unit (str, optional): Unit.
        ref (str, optional): TIMESYS or photcal reference.
        field_id (str, optional): FIELD ID.
        description (str, optional): IRSA field description.
    """
    field = ET.SubElement(table, f"{{{_NS}}}FIELD")
    field.set("name", name)
    field.set("datatype", datatype)
    if ucd:
        field.set("ucd", ucd)
    if unit:
        field.set("unit", unit)
    if ref:
        field.set("ref", ref)
    if field_id:
        field.set("ID", field_id)
    if description:
        desc = ET.SubElement(field, f"{{{_NS}}}DESCRIPTION")
        desc.text = description


def resolve_lookup_name_for_fetch(
    context: DiscoveryFetchContext | None,
) -> str | None:
    """Returns lookup metadata when a named Simbad cone row is close enough.

    Args:
        context (DiscoveryFetchContext, optional): Discovery session context.

    Returns:
        str or None: Lookup label or ``None`` when association does not apply.
    """
    return resolve_lookup_name_for_discovery_fetch(
        context,
        max_association_arcsec=config.LOOKUP_ASSOCIATION_MAX_ARCSEC,
    )
