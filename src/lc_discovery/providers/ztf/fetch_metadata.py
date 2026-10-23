"""Lookup-aware metadata enrichment for fetched ZTF lightcurves."""

from __future__ import annotations

import io
import logging
import warnings

import numpy as np
import pandas as pd
from astropy import units as u
from astropy.table import MaskedColumn, Table
from volightcurve import PhotCal, PhotDM, PhotometryFilter, write_vo_lightcurve

from lc_discovery.discovery_fetch_context import (
    DiscoveryFetchContext,
    effective_lookup_association_arcsec as _shared_effective_lookup_association_arcsec,
    resolve_lookup_name_for_discovery_fetch,
)
from lc_discovery.providers.ztf import config
from lc_discovery.epoch import JD_TO_MJD

logger = logging.getLogger(__name__)

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
# VOTable datatype of the IRSA FIELD to the numpy type of the issued column.
_NUMPY_DTYPES = {
    "double": np.float64,
    "float": np.float32,
    "long": np.int64,
    "int": np.int32,
    "short": np.int16,
    "unsignedByte": np.uint8,
    "unsignedShort": np.uint16,
    "unsignedInt": np.uint32,
}
# Text and logical types: kept as the archive declares them.
_TEXT_DATATYPES = {"char", "unicodeChar"}
_BOOLEAN_DATATYPE = "boolean"


def votable_from_epochs(
    frame: pd.DataFrame,
    *,
    filtercode: str,
    ra_deg: float | None,
    dec_deg: float | None,
) -> bytes:
    """Writes one ZTF light curve as a calibrated VOTable, through ``volightcurve``.

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

    output_columns = [item for item in _COLUMNS if item[0] == time_source or item[0] not in ("hjd", "hmjd")]
    out = Table()
    for position, (source, out_name) in enumerate(output_columns):
        remote = fields.get(source) or {}
        datatype = str(remote.get("datatype") or "double")
        texts = [values[position] for values in kept]
        column = _column_from_cells(out_name, texts, datatype)
        if remote.get("unit"):
            column.unit = _vounit(out_name, remote["unit"])
        if remote.get("description"):
            column.description = remote["description"]
        ucd = _issued_ucd(out_name, remote.get("ucd"))
        column.info.meta = {"ucd": ucd} if ucd else {}
        out[out_name] = column

    photometry_filter = PhotometryFilter(
        filter_id=band.filter_identifier,
        spectral_location=(band.effective_wavelength_angstrom * u.AA).to(u.m),
    )
    calibration = PhotDM(
        photcal=PhotCal(
            zp_flux=band.zp_flux_jy,
            zp_flux_unit="Jy",
            zp_mag=0.0,
            zp_mag_unit="mag",
            mag_sys=band.mag_sys,
        ),
        photometry_filter=photometry_filter,
    )
    oid_text = _cell(frame["oid"].iloc[0], integral=True)
    buffer = io.BytesIO()
    write_vo_lightcurve(
        buffer,
        out,
        f"{config.format_ztf_oid_name(oid_text)} {band.filter_name}",
        refposition=config.ZTF_REFPOSITION,
        timescale=config.ZTF_TIMESCALE,
        timeorigin=timeorigin,
        ra=None if ra_deg is None else float(ra_deg),
        dec=None if dec_deg is None else float(dec_deg),
        binary=False,
        photdms={"mag": calibration, "mag_err": calibration},
    )
    logger.info(
        "%s issued filter=%s n_rows=%s time=%s",
        config.DISPLAY_NAME,
        band.filtercode,
        len(kept),
        time_source,
    )
    return buffer.getvalue()


def _column_from_cells(name: str, texts: list[str], datatype: str) -> MaskedColumn:
    """Builds one typed column from cell texts; an empty numeric or logical cell is masked.

    Args:
        name (str): Issued column name.
        texts (list[str]): Cell texts, ``""`` for a missing value.
        datatype (str): VOTable datatype of the source FIELD.

    Returns:
        astropy.table.MaskedColumn: Column of the type that matches ``datatype``.

    Raises:
        ValueError: When the datatype is none of the numeric, text or boolean VOTable types
            (the complex types and ``bit`` are not handled).
    """
    if datatype in _TEXT_DATATYPES:
        return MaskedColumn(np.array(texts, dtype=str), name=name, mask=[False] * len(texts))
    mask = [text == "" for text in texts]
    if datatype == _BOOLEAN_DATATYPE:
        truth = {"1": True, "t": True, "true": True, "0": False, "f": False, "false": False}
        try:
            filled = [truth[text.strip().lower()] if text != "" else False for text in texts]
        except KeyError as exc:
            raise ValueError(f"{config.DISPLAY_NAME}: column {name!r} has a boolean cell {exc}.") from exc
        return MaskedColumn(np.array(filled, dtype=bool), name=name, mask=mask)
    if datatype not in _NUMPY_DTYPES:
        raise ValueError(f"{config.DISPLAY_NAME}: column {name!r} has unsupported datatype {datatype!r}.")
    # Base 0: IRSA writes some integral cells in hexadecimal (``0x10``), which VOTable allows.
    parse = (lambda text: int(text, 0)) if datatype in _INTEGRAL_DATATYPES else float
    filled = [parse(text) if text != "" else 0 for text in texts]
    values = np.array(filled).astype(_NUMPY_DTYPES[datatype])
    return MaskedColumn(values, name=name, mask=mask)


def _vounit(name: str, text: str) -> u.UnitBase:
    """Returns the unit of an IRSA FIELD, keeping the archive's text.

    A text that Astropy parses as VOUnits without a warning becomes a regular unit (written in
    its VOUnits form). Any other text, including a unit VOUnits does not know or has deprecated,
    is kept as an unrecognised unit and is written exactly as the archive sent it.

    Args:
        name (str): Issued column name, for the log message.
        text (str): Unit text as the archive wrote it.

    Returns:
        astropy.units.UnitBase: The unit, possibly an ``UnrecognizedUnit`` that carries ``text``.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            unit = u.Unit(text, format="vounit")
        except ValueError:
            unit = None
    if unit is None or any(issubclass(item.category, u.UnitsWarning) for item in caught):
        logger.warning(
            "%s column %r keeps the archive unit %r (not plain VOUnits).", config.DISPLAY_NAME, name, text
        )
        return u.UnrecognizedUnit(text)
    return unit


def _issued_ucd(column: str, ucd: str | None) -> str | None:
    """Returns the UCD to issue for a column.

    A column of ``config.NON_PHOTOMETRY_COLUMNS`` keeps the words the server sent
    except the ``phot.*`` ones (``limitmag``: ``instr.sensitivity`` stays, ``phot.mag`` goes).

    Args:
        column (str): Issued column name.
        ucd (str, optional): UCD as the server sent it.

    Returns:
        str or None: UCD for the FIELD, or ``None`` when there is none.
    """
    if not ucd:
        return None
    if column not in config.NON_PHOTOMETRY_COLUMNS:
        return ucd
    words = [word for word in ucd.split(";") if not word.strip().startswith("phot.")]
    return ";".join(words) or None


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
