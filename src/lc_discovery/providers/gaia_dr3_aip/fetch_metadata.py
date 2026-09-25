"""Turn a Gaia AIP epoch-photometry VOTable into one band light curve."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET

from lc_discovery.providers.gaia_dr3_aip import config
from lc_discovery.shared.gaia_epoch_mag_error import mag_error_from_flux_over_error

logger = logging.getLogger(__name__)

_NS = "http://www.ivoa.net/xml/VOTable/v1.3"
_UT_FILTER = "photDM:PhotometryFilter.identifier"
_UT_FLUX = "photDM:PhotCal.zeroPoint.flux.value"
_UT_MAG = "photDM:PhotCal.zeroPoint.referenceMagnitude.value"
_UT_SYS = "photDM:PhotCal.magnitudeSystem.type"
_UT_WAVE = "photDM:PhotometryFilter.spectralLocation.value"

# Short Jy zero points and wavelengths from the reference light curves.
# Filter Profile Service is the source of the magnitude-column flux zero point
# and the filter parameters. Magnitude zero point on that photcal is 0 mag.
_BANDS = {
    "G": {
        "filter_id": "GAIA/GAIA3.G",
        "zp_flux_jy": "3228.75",
        "wavelength_m": "5.82e-7",
        "mag_ucd": "phot.mag;em.opt",
        "time_in": "g_transit_time",
        "time_out": "transit_time",
        "snr_in": "g_transit_flux_over_error",
        "snr_out": "transit_flux_over",
        "mag_in": "g_transit_mag",
        "mag_out": "transit_mag",
        "extra": (("g_transit_n_obs", "transit_n_obs", "meta.number"),),
    },
    "BP": {
        "filter_id": "GAIA/GAIA3.Gbp",
        "zp_flux_jy": "3552.01",
        "wavelength_m": "5.04e-7",
        "mag_ucd": "phot.mag;em.opt.B",
        "time_in": "bp_obs_time",
        "time_out": "obs_time",
        "snr_in": "bp_flux_over_error",
        "snr_out": "flux_over",
        "mag_in": "bp_mag",
        "mag_out": "mag",
        "extra": (),
    },
    "RP": {
        "filter_id": "GAIA/GAIA3.Grp",
        "zp_flux_jy": "2554.95",
        "wavelength_m": "7.62e-7",
        "mag_ucd": "phot.mag;em.opt.R",
        "time_in": "rp_obs_time",
        "time_out": "obs_time",
        "snr_in": "rp_flux_over_error",
        "snr_out": "flux_over",
        "mag_in": "rp_mag",
        "mag_out": "mag",
        "extra": (),
    },
}


def _local(tag: str) -> str:
    """Returns an XML tag without its namespace.

    Args:
        tag (str): Element tag.

    Returns:
        str: Local name.
    """
    return tag.rsplit("}", 1)[-1]


def _cells(text: str | None) -> list[str]:
    """Splits one TAP array cell into tokens.

    Args:
        text (str or None): TABLEDATA cell text.

    Returns:
        list[str]: Tokens, with an empty list for a blank cell.
    """
    if text is None or not str(text).strip():
        return []
    return str(text).split()


def _arrays_from_votable(payload: bytes) -> dict[str, list[str] | str]:
    """Reads the epoch-photometry arrays from a TAP VOTable.

    Args:
        payload (bytes): TAP result for ``gaiadr3.epoch_photometry``.

    Returns:
        dict: ``source_id`` and one token list per field name.

    Raises:
        ValueError: When the document is not the expected single-row table.
    """
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ValueError(f"{config.DISPLAY_NAME}: downloaded product is not XML: {exc}") from exc
    tables = [element for element in root.iter() if _local(element.tag) == "TABLE"]
    if len(tables) != 1:
        raise ValueError(f"{config.DISPLAY_NAME}: epoch photometry VOTable has no single TABLE.")
    table = tables[0]
    fields = [field.get("name") for field in table if _local(field.tag) == "FIELD"]
    rows = [row for row in table.iter() if _local(row.tag) == "TR"]
    if len(rows) != 1:
        raise ValueError(f"{config.DISPLAY_NAME}: epoch photometry VOTable is not one source row.")
    cells = [child for child in list(rows[0]) if _local(child.tag) == "TD"]
    if len(cells) != len(fields):
        raise ValueError(f"{config.DISPLAY_NAME}: epoch photometry row does not match its fields.")
    found: dict[str, list[str] | str] = {}
    for name, cell in zip(fields, cells):
        if name == "source_id":
            found["source_id"] = (cell.text or "").strip()
        else:
            found[name] = _cells(cell.text)
    return found


def votable_for_band(epoch: dict, band_code: str) -> bytes:
    """Builds one band light curve VOTable from epoch-photometry arrays.

    Args:
        epoch (dict): ``source_id`` and archive array columns.
        band_code (str): ``G``, ``BP``, or ``RP``.

    Returns:
        bytes: Single-band VOTable.

    Raises:
        ValueError: When the band or a required array is missing.
    """
    spec = _BANDS.get(str(band_code).strip().upper())
    if spec is None:
        raise ValueError(f"{config.DISPLAY_NAME}: unsupported band {band_code!r}.")
    source_id = str(epoch.get("source_id") or "").strip()
    if not source_id:
        raise ValueError(f"{config.DISPLAY_NAME}: epoch photometry is missing source_id.")
    columns = [spec["time_in"], spec["snr_in"], spec["mag_in"]]
    columns.extend(item[0] for item in spec["extra"])
    series = []
    for name in columns:
        values = epoch.get(name)
        if not isinstance(values, list):
            raise ValueError(f"{config.DISPLAY_NAME}: column {name} is missing.")
        series.append(values)
    length = len(series[0])
    if any(len(values) != length for values in series):
        raise ValueError(f"{config.DISPLAY_NAME}: band {spec['filter_id']} arrays differ in length.")

    kept = [
        index
        for index in range(length)
        if not _is_missing(series[0][index]) and not _is_missing(series[2][index])
    ]
    snr_kept = [series[1][index] for index in kept]
    mag_err = mag_error_from_flux_over_error(snr_kept)
    ET.register_namespace("", _NS)
    root = ET.Element(f"{{{_NS}}}VOTABLE", {"version": "1.3"})
    resource = ET.SubElement(root, f"{{{_NS}}}RESOURCE")
    timesys = ET.SubElement(resource, f"{{{_NS}}}TIMESYS")
    timesys.set("ID", "ts")
    timesys.set("refposition", "BARYCENTER")
    timesys.set("timeorigin", "2455197.5")
    timesys.set("timescale", "TCB")
    group = ET.SubElement(resource, f"{{{_NS}}}GROUP")
    group.set("ID", "phot_def")
    group.set("name", "photcal")
    _param(group, "filterIdentifier", spec["filter_id"], utype=_UT_FILTER, arraysize="*")
    _param(group, "zeroPointFlux", spec["zp_flux_jy"], utype=_UT_FLUX, unit="Jy", datatype="double")
    _param(group, "magnitudeSystem", "Vega", utype=_UT_SYS, arraysize="*")
    _param(
        group,
        "effectiveWavelength",
        spec["wavelength_m"],
        utype=_UT_WAVE,
        unit="m",
        datatype="double",
    )
    _param(
        group,
        "zeroPointReferenceMagnitude",
        str(config.GAIA_AIP_ZERO_POINT_REFERENCE_MAGNITUDE),
        utype=_UT_MAG,
        unit="mag",
        datatype="double",
    )
    mag_id = spec["mag_out"]
    fieldref = ET.SubElement(group, f"{{{_NS}}}FIELDref")
    fieldref.set("ref", mag_id)

    table = ET.SubElement(resource, f"{{{_NS}}}TABLE")
    table.set("name", f"Gaia DR3 {source_id} {spec['filter_id']}")
    source = ET.SubElement(table, f"{{{_NS}}}PARAM")
    source.set("name", "source_id")
    source.set("datatype", "long")
    source.set("value", source_id)
    _field(table, spec["time_out"], "double", ucd="time.epoch", unit="d", ref="ts")
    _field(table, mag_id, "double", ucd=spec["mag_ucd"], unit="mag", ref="phot_def", field_id=mag_id)
    _field(table, "mag_error", "double", ucd="stat.error;phot.mag", unit="mag", ref="phot_def")
    _field(table, spec["snr_out"], "double", ucd="stat.snr;phot.flux")
    for _archive_name, out_name, ucd in spec["extra"]:
        _field(table, out_name, "double", ucd=ucd)

    data = ET.SubElement(table, f"{{{_NS}}}DATA")
    tabledata = ET.SubElement(data, f"{{{_NS}}}TABLEDATA")
    for row_index, index in enumerate(kept):
        row = ET.SubElement(tabledata, f"{{{_NS}}}TR")
        tokens = [series[0][index], series[2][index], _number(mag_err[row_index]), series[1][index]]
        tokens.extend(values[index] for values in series[3:])
        for token in tokens:
            cell = ET.SubElement(row, f"{{{_NS}}}TD")
            text = "" if token is None else str(token).strip()
            if text.lower() == "nan":
                text = ""
            cell.text = text

    logger.info(
        "%s issued band=%s filter=%s n_rows=%s zp_flux=%s Jy zp_mag=%s",
        config.DISPLAY_NAME,
        band_code,
        spec["filter_id"],
        len(kept),
        spec["zp_flux_jy"],
        config.GAIA_AIP_ZERO_POINT_REFERENCE_MAGNITUDE,
    )
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def enrich_votable(payload: bytes, *, band_code: str) -> bytes:
    """Issues one Gaia DR3 AIP band from a TAP epoch-photometry VOTable.

    Args:
        payload (bytes): TAP result.
        band_code (str): Catalogue band ``G``, ``BP``, or ``RP``.

    Returns:
        bytes: Single-band VOTable.
    """
    return votable_for_band(_arrays_from_votable(payload), band_code)


def votable_from_cached_epoch(epoch: dict, *, band_code: str) -> bytes:
    """Issues one band from the prefetch cache of epoch arrays.

    Args:
        epoch (dict): Cached epoch-photometry arrays.
        band_code (str): Catalogue band.

    Returns:
        bytes: Single-band VOTable.
    """
    copied = {"source_id": epoch.get("source_id")}
    for key, value in epoch.items():
        if key == "source_id":
            continue
        if isinstance(value, list):
            copied[key] = ["" if item is None else str(item) for item in value]
        else:
            copied[key] = value
    return votable_for_band(copied, band_code)


def _is_missing(value) -> bool:
    """True when a time or magnitude token is absent or NaN.

    Args:
        value: One array token.

    Returns:
        bool: Whether the epoch must be dropped.
    """
    if value is None:
        return True
    text = str(value).strip().lower()
    if text in {"", "nan", "none"}:
        return True
    try:
        number = float(text)
    except ValueError:
        return False
    return number != number


def _number(value: float) -> str:
    """Formats one magnitude error, leaving invalid ratios empty.

    Args:
        value (float): Magnitude uncertainty.

    Returns:
        str: Decimal text, or an empty string when the value is not finite.
    """
    if value != value:
        return ""
    return repr(float(value))


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
        ref (str, optional): Reference to a TIMESYS or photcal group.
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
