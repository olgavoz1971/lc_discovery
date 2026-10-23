"""Turn a Gaia AIP epoch-photometry VOTable into one band light curve."""

from __future__ import annotations

import io
import logging
import xml.etree.ElementTree as ET

import numpy as np
from astropy import units as u
from astropy.table import MaskedColumn, Table
from volightcurve import PhotCal, PhotDM, PhotometryFilter, write_vo_lightcurve

from lc_discovery.providers.gaia_dr3_aip import config
from lc_discovery.shared.gaia_epoch_mag_error import mag_error_from_flux_over_error

logger = logging.getLogger(__name__)

_NS = "http://www.ivoa.net/xml/VOTable/v1.3"  # the TAP download is parsed with ElementTree

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
    """Builds one band light curve VOTable from epoch-photometry arrays, through ``volightcurve``.

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
    mag_id = spec["mag_out"]
    out = Table()
    out[spec["time_out"]] = _column(series[0], kept, spec["time_out"], unit="d", ucd="time.epoch")
    out[mag_id] = _column(series[2], kept, mag_id, unit="mag", ucd=spec["mag_ucd"])
    out["mag_error"] = MaskedColumn(
        np.ma.masked_invalid(np.array(mag_err, dtype=float)),
        name="mag_error",
        unit="mag",
    )
    out["mag_error"].info.meta = {"ucd": "stat.error;phot.mag"}
    out[spec["snr_out"]] = _column(series[1], kept, spec["snr_out"], ucd="stat.snr;phot.flux")
    for position, (_archive_name, out_name, ucd) in enumerate(spec["extra"], start=3):
        out[out_name] = _column(series[position], kept, out_name, ucd=ucd)

    calibration = PhotDM(
        photcal=PhotCal(
            zp_flux=float(spec["zp_flux_jy"]),
            zp_flux_unit="Jy",
            zp_mag=float(config.GAIA_AIP_ZERO_POINT_REFERENCE_MAGNITUDE),
            zp_mag_unit="mag",
            mag_sys="Vega",
        ),
        photometry_filter=PhotometryFilter(
            filter_id=spec["filter_id"],
            spectral_location=(float(spec["wavelength_m"]) * u.m),
        ),
    )
    buffer = io.BytesIO()
    write_vo_lightcurve(
        buffer,
        out,
        f"Gaia DR3 {source_id} {spec['filter_id']}",
        refposition="BARYCENTER",
        timescale="TCB",
        timeorigin=2455197.5,
        binary=False,
        photdms={mag_id: calibration, "mag_error": calibration},
        table_params=[{"name": "source_id", "value": source_id, "datatype": "long"}],
    )
    logger.info(
        "%s issued band=%s filter=%s n_rows=%s zp_flux=%s Jy zp_mag=%s",
        config.DISPLAY_NAME,
        band_code,
        spec["filter_id"],
        len(kept),
        spec["zp_flux_jy"],
        config.GAIA_AIP_ZERO_POINT_REFERENCE_MAGNITUDE,
    )
    return buffer.getvalue()


def _column(
    tokens: list[str], kept: list[int], name: str, *, ucd: str, unit: str | None = None
) -> MaskedColumn:
    """Builds one double column from archive tokens; a NaN or blank token is masked.

    Args:
        tokens (list[str]): All tokens of the archive array.
        kept (list[int]): Indices of the epochs that are issued.
        name (str): Issued column name.
        ucd (str): UCD of the column.
        unit (str, optional): Unit of the column.

    Returns:
        astropy.table.MaskedColumn: Double column in the order of ``kept``.
    """
    values = []
    mask = []
    for index in kept:
        text = "" if tokens[index] is None else str(tokens[index]).strip()
        missing = _is_missing(text)
        values.append(0.0 if missing else float(text))
        mask.append(missing)
    column = MaskedColumn(np.array(values, dtype=float), name=name, mask=mask)
    if unit:
        column.unit = unit
    column.info.meta = {"ucd": ucd}
    return column


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
