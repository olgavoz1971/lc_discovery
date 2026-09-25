"""Pan-STARRS1 DR2 detection table written as one calibrated VOTable."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET

import numpy as np
from astropy.table import Table

from lc_discovery.providers.panstarrs1_dr2 import config
from lc_discovery.providers.panstarrs1_dr2.mean_object_epoch import (
    coosys_epoch_year_from_detection_table,
)
from lc_discovery.providers.panstarrs1_dr2.ps1_names import format_ps1_object_name

logger = logging.getLogger(__name__)

_NS = "http://www.ivoa.net/xml/VOTable/v1.3"
_UT_FILTER = "photDM:PhotometryFilter.identifier"
_UT_FLUX = "photDM:PhotCal.zeroPoint.flux.value"
_UT_MAG = "photDM:PhotCal.zeroPoint.referenceMagnitude.value"
_UT_SYS = "photDM:PhotCal.magnitudeSystem.type"
_UT_WAVE = "photDM:PhotometryFilter.spectralLocation.value"


def votable_from_detections(
    detection_table: Table,
    *,
    obj_id: int,
    filter_name: str,
    ra_deg: float,
    dec_deg: float,
) -> bytes:
    """Writes one Pan-STARRS1 filter as a calibrated VOTable.

    A row is removed when time or flux is missing. A missing flux error stays
    an empty cell. Flux numbers stay in Jy.

    Args:
        detection_table (astropy.table.Table): TAP detection rows for one filter.
        obj_id (int): Pan-STARRS mean object identifier.
        filter_name (str): ``g``, ``r``, ``i``, ``z``, or ``y``.
        ra_deg (float): Mean-object right ascension in degrees.
        dec_deg (float): Mean-object declination in degrees.

    Returns:
        bytes: Calibrated VOTable.

    Raises:
        ValueError: When the table has no usable rows or required columns.
    """
    if detection_table is None or len(detection_table) == 0:
        raise ValueError(
            f"{config.DISPLAY_NAME}: no detection epochs for objID={obj_id} "
            f"filter={filter_name!r} after quality cuts."
        )
    band = config.band_spec_for_filter_name(filter_name)
    columns = {str(name).lower(): str(name) for name in detection_table.colnames}
    for logical in ("obstime", "psfflux", "psffluxerr"):
        if logical not in columns:
            raise ValueError(
                f"{config.DISPLAY_NAME}: detection table missing column {logical}."
            )
    coosys_epoch = coosys_epoch_year_from_detection_table(detection_table, column_map=columns)
    kept: list[tuple[str, str, str]] = []
    for row in detection_table:
        time_text = _number(row[columns["obstime"]])
        flux_text = _number(row[columns["psfflux"]])
        if time_text == "" or flux_text == "":
            continue
        kept.append((time_text, flux_text, _number(row[columns["psffluxerr"]])))
    if not kept:
        raise ValueError(
            f"{config.DISPLAY_NAME}: no epochs with time and flux for objID={obj_id} "
            f"filter={filter_name!r}."
        )

    label = format_ps1_object_name(obj_id)
    description = config.detection_lightcurve_description(
        obj_id=obj_id,
        filter_name=band.filter_name,
    )
    wavelength_m = band.effective_wavelength_angstrom * 1e-10
    ET.register_namespace("", _NS)
    root = ET.Element(f"{{{_NS}}}VOTABLE", {"version": "1.3"})
    resource = ET.SubElement(root, f"{{{_NS}}}RESOURCE")
    coosys = ET.SubElement(resource, f"{{{_NS}}}COOSYS")
    coosys.set("ID", "system")
    coosys.set("system", config.COOSYS_SYSTEM)
    coosys.set("epoch", repr(coosys_epoch))
    timesys = ET.SubElement(resource, f"{{{_NS}}}TIMESYS")
    timesys.set("ID", "ts")
    timesys.set("refposition", config.REFPOSITION)
    timesys.set("timescale", config.TIMESCALE)
    timesys.set("timeorigin", str(config.TIMEORIGIN_MJD))
    group = ET.SubElement(resource, f"{{{_NS}}}GROUP")
    group.set("ID", "photcal")
    group.set("name", "photcal")
    _param(group, "filterIdentifier", band.filter_identifier, utype=_UT_FILTER, arraysize="*")
    _param(group, "zeroPointFlux", repr(float(config.AB_REFERENCE_FLUX_JY)), utype=_UT_FLUX, unit="Jy", datatype="double")
    _param(group, "magnitudeSystem", config.MAG_SYSTEM, utype=_UT_SYS, arraysize="*")
    _param(group, "effectiveWavelength", repr(float(wavelength_m)), utype=_UT_WAVE, unit="m", datatype="double")
    _param(group, "zeroPointReferenceMagnitude", "0.0", utype=_UT_MAG, unit="mag", datatype="double")
    for field_id in ("psf_flux", "psf_flux_error"):
        fieldref = ET.SubElement(group, f"{{{_NS}}}FIELDref")
        fieldref.set("ref", field_id)

    table = ET.SubElement(resource, f"{{{_NS}}}TABLE")
    table.set("name", f"{label} {band.filter_name}")
    desc = ET.SubElement(table, f"{{{_NS}}}DESCRIPTION")
    desc.text = description
    _table_param(table, "facility_name", config.FACILITY_NAME)
    _table_param(table, "instrument_name", config.INSTRUMENT_NAME)
    _table_param(table, "bibcode", config.PUBLICATION_BIBCODE, ucd="meta.bib.bibcode")
    _table_param(table, "ra", repr(float(ra_deg)), datatype="double", ucd="pos.eq.ra")
    _table_param(table, "dec", repr(float(dec_deg)), datatype="double", ucd="pos.eq.dec")
    _field(table, "obs_time", "double", ucd="time.epoch", unit="d", ref="ts", field_id="obs_time")
    _field(table, "psf_flux", "double", ucd="phot.flux;em.opt", unit="Jy", ref="photcal", field_id="psf_flux")
    _field(
        table,
        "psf_flux_error",
        "double",
        ucd="stat.error;phot.flux",
        unit="Jy",
        ref="photcal",
        field_id="psf_flux_error",
    )
    data = ET.SubElement(table, f"{{{_NS}}}DATA")
    tabledata = ET.SubElement(data, f"{{{_NS}}}TABLEDATA")
    for time_text, flux_text, err_text in kept:
        row = ET.SubElement(tabledata, f"{{{_NS}}}TR")
        for text in (time_text, flux_text, err_text):
            cell = ET.SubElement(row, f"{{{_NS}}}TD")
            cell.text = text
    logger.info(
        "%s issued obj_id=%s filter=%s n_rows=%s",
        config.DISPLAY_NAME,
        obj_id,
        band.filter_name,
        len(kept),
    )
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _number(value) -> str:
    """Formats one finite number, or an empty cell when it is missing.

    Args:
        value: Table cell.

    Returns:
        str: Decimal text, or an empty string.
    """
    if value is None or (isinstance(value, float) and value != value):
        return ""
    if isinstance(value, np.ma.core.MaskedConstant) or np.ma.is_masked(value):
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if number != number:
        return ""
    return repr(number)


def _table_param(
    table: ET.Element,
    name: str,
    value: str,
    *,
    datatype: str = "char",
    ucd: str | None = None,
) -> None:
    """Appends one TABLE PARAM.

    Args:
        table (xml.etree.ElementTree.Element): TABLE element.
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


def _param(
    parent: ET.Element,
    name: str,
    value: str,
    *,
    utype: str,
    unit: str | None = None,
    datatype: str = "char",
    arraysize: str | None = None,
) -> None:
    """Appends one photcal PARAM.

    Args:
        parent (xml.etree.ElementTree.Element): Photcal GROUP.
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


def _field(
    table: ET.Element,
    name: str,
    datatype: str,
    *,
    ucd: str,
    unit: str | None = None,
    ref: str | None = None,
    field_id: str | None = None,
) -> None:
    """Appends one FIELD.

    Args:
        table (xml.etree.ElementTree.Element): TABLE element.
        name (str): Column name.
        datatype (str): VOTable datatype.
        ucd (str): Column UCD.
        unit (str, optional): Unit.
        ref (str, optional): TIMESYS or photcal reference.
        field_id (str, optional): FIELD ID.
    """
    field = ET.SubElement(table, f"{{{_NS}}}FIELD")
    field.set("name", name)
    field.set("datatype", datatype)
    field.set("ucd", ucd)
    if unit:
        field.set("unit", unit)
    if ref:
        field.set("ref", ref)
    if field_id:
        field.set("ID", field_id)
