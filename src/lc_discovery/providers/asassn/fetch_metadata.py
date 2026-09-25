"""ASAS-SN photometry table written as one calibrated VOTable."""

from __future__ import annotations

import logging
import math
import xml.etree.ElementTree as ET

import pandas as pd

from lc_discovery.providers.asassn import config
from lc_discovery.shared.photcal_error_link import (
    share_photcal_with_unlinked_errors,
)
from skvo_veb.utils.my_tools import PipeException
from volightcurve import VOLightCurve

_NS = "http://www.ivoa.net/xml/VOTable/v1.3"
_UT_FILTER = "photDM:PhotometryFilter.identifier"
_UT_FLUX = "photDM:PhotCal.zeroPoint.flux.value"
_UT_MAG = "photDM:PhotCal.zeroPoint.referenceMagnitude.value"
_UT_SYS = "photDM:PhotCal.magnitudeSystem.type"
_UT_WAVE = "photDM:PhotometryFilter.spectralLocation.value"
_MJY_TO_JY = 1.0e-3

logger = logging.getLogger(__name__)


def votable_from_band_table(
    band_table: pd.DataFrame,
    *,
    band_code: str,
    asas_sn_id: int | str,
    ra_deg: float | None,
    dec_deg: float | None,
    epoch_jd: float | None,
    period_days: float | None,
) -> bytes:
    """Writes one ASAS-SN band as a calibrated VOTable.

    Flux and flux error are converted from mJy to Jy. A missing flux error
    stays an empty cell. Rows without time or flux are already removed.

    Args:
        band_table (pandas.DataFrame): One band, columns ``jd``, ``flux``,
            ``flux_err``, and optionally ``camera``.
        band_code (str): ``g`` or ``V``.
        asas_sn_id (int or str): Sky Patrol source identifier.
        ra_deg (float or None): Object right ascension in degrees.
        dec_deg (float or None): Object declination in degrees.
        epoch_jd (float or None): Folding epoch. Omitted when absent.
        period_days (float or None): Folding period in days. Omitted when absent.

    Returns:
        bytes: VOTable for this band.
    """
    band = config.band_spec_for_code(band_code)
    sid = int(asas_sn_id)
    ET.register_namespace("", _NS)
    root = ET.Element(f"{{{_NS}}}VOTABLE", {"version": "1.3"})
    resource = ET.SubElement(root, f"{{{_NS}}}RESOURCE")
    timesys = ET.SubElement(resource, f"{{{_NS}}}TIMESYS")
    timesys.set("ID", "ts")
    timesys.set("refposition", config.ASASSN_REFPOSITION)
    timesys.set("timescale", config.ASASSN_TIMESCALE)
    timesys.set("timeorigin", "0")
    group = ET.SubElement(resource, f"{{{_NS}}}GROUP")
    group.set("ID", "photcal")
    group.set("name", "photcal")
    _param(group, "filterIdentifier", band.filter_identifier, utype=_UT_FILTER, arraysize="*")
    _param(
        group,
        "zeroPointFlux",
        repr(float(band.zp_flux_jy)),
        utype=_UT_FLUX,
        unit="Jy",
        datatype="double",
    )
    _param(group, "magnitudeSystem", band.mag_sys, utype=_UT_SYS, arraysize="*")
    _param(
        group,
        "effectiveWavelength",
        repr(float(band.effective_wavelength_m)),
        utype=_UT_WAVE,
        unit="m",
        datatype="double",
    )
    _param(group, "zeroPointReferenceMagnitude", "0.0", utype=_UT_MAG, unit="mag", datatype="double")
    flux_ref = ET.SubElement(group, f"{{{_NS}}}FIELDref")
    flux_ref.set("ref", "flux")
    err_ref = ET.SubElement(group, f"{{{_NS}}}FIELDref")
    err_ref.set("ref", "flux_err")

    table = ET.SubElement(resource, f"{{{_NS}}}TABLE")
    table.set("name", f"ASAS-SN {sid} {band.filter_identifier}")
    _table_param(table, "asas_sn_id", str(sid), datatype="long")
    if ra_deg is not None:
        _table_param(table, "ra", repr(float(ra_deg)), datatype="double", ucd="pos.eq.ra")
    if dec_deg is not None:
        _table_param(table, "dec", repr(float(dec_deg)), datatype="double", ucd="pos.eq.dec")
    if period_days is not None:
        _table_param(
            table,
            "period",
            repr(float(period_days)),
            datatype="double",
            unit="d",
            ucd="src.var;time.period",
        )
    if epoch_jd is not None:
        _table_param(
            table,
            "epoch",
            repr(float(epoch_jd)),
            datatype="double",
            unit="d",
            ucd="time.epoch",
            ref="ts",
        )
    _field(table, "jd", "double", ucd="time.epoch", unit="d", ref="ts", field_id="jd")
    _field(table, "flux", "double", ucd="phot.flux;em.opt", unit="Jy", ref="photcal", field_id="flux")
    _field(
        table,
        "flux_err",
        "double",
        ucd="stat.error;phot.flux",
        unit="Jy",
        ref="photcal",
        field_id="flux_err",
    )
    has_camera = "camera" in band_table.columns
    if has_camera:
        _field(table, "camera", "char", arraysize="*")

    data = ET.SubElement(table, f"{{{_NS}}}DATA")
    tabledata = ET.SubElement(data, f"{{{_NS}}}TABLEDATA")
    for _, row in band_table.iterrows():
        tr = ET.SubElement(tabledata, f"{{{_NS}}}TR")
        _cell(tr, _jy(row["jd"], scale=1.0))
        _cell(tr, _jy(row["flux"], scale=_MJY_TO_JY))
        _cell(tr, _jy(row["flux_err"], scale=_MJY_TO_JY))
        if has_camera:
            camera = row["camera"]
            text = "" if camera is None or (isinstance(camera, float) and math.isnan(camera)) else str(camera)
            _cell(tr, text)

    logger.info(
        "%s issued asas_sn_id=%s band=%s filter=%s n_rows=%s",
        config.DISPLAY_NAME,
        sid,
        band.band_code,
        band.filter_identifier,
        len(band_table),
    )
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _jy(value, *, scale: float) -> str:
    """Formats one finite number, or an empty cell when it is missing.

    Args:
        value: Cell value.
        scale (float): Multiplier applied before writing.

    Returns:
        str: Decimal text, or an empty string.
    """
    try:
        number = float(value) * scale
    except (TypeError, ValueError):
        return ""
    if number != number:
        return ""
    return repr(number)


def _cell(row: ET.Element, text: str) -> None:
    """Appends one TABLEDATA cell.

    Args:
        row (xml.etree.ElementTree.Element): ``TR`` element.
        text (str): Cell text.
    """
    cell = ET.SubElement(row, f"{{{_NS}}}TD")
    cell.text = text


def _table_param(
    table: ET.Element,
    name: str,
    value: str,
    *,
    datatype: str,
    unit: str | None = None,
    ucd: str | None = None,
    ref: str | None = None,
) -> None:
    """Appends one TABLE PARAM.

    Args:
        table (xml.etree.ElementTree.Element): TABLE element.
        name (str): PARAM name.
        value (str): PARAM value.
        datatype (str): VOTable datatype.
        unit (str, optional): Unit.
        ucd (str, optional): UCD.
        ref (str, optional): TIMESYS reference.
    """
    param = ET.SubElement(table, f"{{{_NS}}}PARAM")
    param.set("name", name)
    param.set("datatype", datatype)
    param.set("value", value)
    if unit:
        param.set("unit", unit)
    if ucd:
        param.set("ucd", ucd)
    if ref:
        param.set("ref", ref)


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
    ucd: str | None = None,
    unit: str | None = None,
    ref: str | None = None,
    field_id: str | None = None,
    arraysize: str | None = None,
) -> None:
    """Appends one FIELD.

    Args:
        table (xml.etree.ElementTree.Element): TABLE element.
        name (str): Column name.
        datatype (str): VOTable datatype.
        ucd (str, optional): Column UCD.
        unit (str, optional): Unit.
        ref (str, optional): TIMESYS or photcal reference.
        field_id (str, optional): FIELD ID.
        arraysize (str, optional): Character arraysize.
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
    if arraysize:
        field.set("arraysize", arraysize)


def enrich_fetched_volightcurve(
    volc: VOLightCurve,
    *,
    band_code: str,
    asas_sn_id: int | str,
) -> VOLightCurve:
    """Applies ASAS-SN pipeline metadata expected by export and ``CurveDash``.

    Args:
        volc (VOLightCurve): Parsed lightcurve from ``build_volightcurve_from_band_table``.
        band_code (str): ``g`` or ``V``.
        asas_sn_id (int or str): Sky Patrol source identifier.

    Returns:
        VOLightCurve: Same instance with normalised ``table.meta``.

    Raises:
        PipeException: When band metadata cannot be resolved.
    """
    band = config.band_spec_for_code(band_code)
    meta = volc.table.meta
    if meta is None:
        volc.table.meta = {}
        meta = volc.table.meta

    title = f"ASAS-SN {int(asas_sn_id)} {band.band_code}"
    meta["name"] = title
    meta["lightcurve_title"] = title
    meta["title"] = title
    meta["authors"] = [config.ASASSN_PIPELINE]
    meta["mission"] = config.PROVIDER_ID
    meta["band"] = band.band_code
    meta["calibration_catalog"] = band.calibration_catalog
    meta["photcal"] = config.photcal_dict_for_band(band.band_code)
    meta["asas_sn_id"] = int(asas_sn_id)

    description = meta.get("description") or meta.get("table_description")
    if not description or not str(description).strip():
        raise PipeException(
            f"{config.DISPLAY_NAME}: lightcurve is missing TABLE description after build."
        )

    logger.debug(
        "%s enriched asas_sn_id=%s band=%s n_points=%s",
        config.DISPLAY_NAME,
        asas_sn_id,
        band.band_code,
        len(volc),
    )
    share_photcal_with_unlinked_errors(volc)
    return volc
