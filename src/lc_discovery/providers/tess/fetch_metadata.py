"""Issue a calibrated VOTable for one TESS archive light curve."""

from __future__ import annotations

import logging
import math
import xml.etree.ElementTree as ET

import numpy as np
import astropy.units as u

from lc_discovery.providers.tess import config
from lc_discovery.providers.tess.columns import (
    ROLE_BACKGROUND,
    ROLE_BACKGROUND_ERROR,
    ZP_MAG_GAIAMAG,
    ZP_MAG_TESSMAG,
    get_background_spec,
    is_known_author,
    is_spoc_family_flux_unit,
    list_present_photometry_specs,
    normalize_lc_column,
    background_role_for_name,
)

logger = logging.getLogger(__name__)

_NS = "http://www.ivoa.net/xml/VOTable/v1.3"
_UT_FILTER = "photDM:PhotometryFilter.identifier"
_UT_FLUX = "photDM:PhotCal.zeroPoint.flux.value"
_UT_MAG = "photDM:PhotCal.zeroPoint.referenceMagnitude.value"
_UT_SYS = "photDM:PhotCal.magnitudeSystem.type"
_UT_WAVE = "photDM:PhotometryFilter.spectralLocation.value"
_TIMESYS_ID = "ts"

UCD_FLUX = "phot.flux"
UCD_FLUX_ERROR = "stat.error;phot.flux"
UCD_MAG = "phot.mag"
UCD_MAG_ERROR = "stat.error;phot.mag"
UCD_BACKGROUND = "instr.background"
UCD_BACKGROUND_ERROR = "stat.error;instr.background"


def votable_from_lightcurve(
    lc,
    *,
    tic: int,
    sector: int,
    author: str,
    exptime: float,
    mast_pointer: dict[str, str] | None = None,
) -> bytes:
    """Writes a calibrated VOTable for one TESS archive light curve.

    Known authors issue registered flux and background columns. Unknown
    authors keep every Lightkurve column; UCDs follow roles documented in
    ``docs/providers/tess.md``. Time is BTJD converted to MJD.

    Args:
        lc: Lightkurve ``LightCurve``.
        tic (int): TESS Input Catalogue number.
        sector (int): TESS sector.
        author (str): Pipeline author.
        exptime (float): MAST cadence in seconds.
        mast_pointer (dict, optional): ``obs_collection``, ``obs_id``,
            ``product_filename`` of the cached FITS. When given, they are
            written as the TABLE PARAMs ``mast_obs_collection``,
            ``mast_obs_id`` and ``mast_product_filename``.

    Returns:
        bytes: Calibrated VOTable.

    Raises:
        ValueError: When time is missing, or a known author has no flux columns.
    """
    _check_time_system(lc)
    time_btjd = _time_btjd(lc)
    if time_btjd is None or len(time_btjd) == 0:
        raise ValueError(f"{config.DISPLAY_NAME}: downloaded product has no TIME.")
    if is_known_author(author):
        issued_columns, photcal_groups = _issued_columns_known_author(lc, author, sector)
    else:
        issued_columns, photcal_groups = _issued_columns_unknown_author(lc)
    if is_known_author(author) and not issued_columns:
        raise ValueError(
            f"{config.DISPLAY_NAME}: {author} sector {sector} has no registered "
            "flux columns in the downloaded product."
        )

    time_mjd = np.asarray([config.btjd_to_mjd(v) for v in time_btjd], dtype=float)
    n_rows = len(time_mjd)
    for name, values, _ucd, _unit, _gid in issued_columns:
        if len(values) != n_rows:
            raise ValueError(
                f"{config.DISPLAY_NAME}: column {name} length {len(values)} "
                f"does not match time length {n_rows}."
            )
    return _votable_xml(
        lc,
        issued_columns=issued_columns,
        photcal_groups=photcal_groups,
        time_mjd=time_mjd,
        tic=tic,
        sector=sector,
        author=author,
        exptime=exptime,
        mast_pointer=mast_pointer,
    )


def _issue_unit(unit: str | None) -> str | None:
    """Returns the unit string to write on an issued FIELD.

    Electron s-1 family units are written in the configured spelling. Other
    units are converted to VOUnit; a unit VOTable cannot express is not
    written (the column is still issued).

    Args:
        unit (str, optional): Unit read from the product.

    Returns:
        str or None: Unit for the FIELD, or ``None``.
    """
    if unit is None:
        return None
    if is_spoc_family_flux_unit(unit):
        return config.TESS_ELECTRON_S_ZERO_POINT_FLUX_UNIT
    try:
        return u.Unit(unit).to_string("vounit")
    except (ValueError, TypeError):
        logger.debug("%s unit %r is not expressible in VOUnit.", config.DISPLAY_NAME, unit)
        return None


def _issued_columns_known_author(lc, author: str, sector: int):
    """Builds issued columns and PhotCal groups for a registered author.

    Args:
        lc: Lightkurve light curve.
        author (str): Pipeline author.
        sector (int): TESS sector.

    Returns:
        tuple: ``(issued_columns, photcal_groups)``.
    """
    colnames = _colnames(lc)
    flux_specs = list_present_photometry_specs(author, sector, colnames)
    issued_columns: list[tuple] = []
    photcal_groups: dict[str, dict] = {}

    for spec in flux_specs:
        flux_name = normalize_lc_column(spec.flux_col)
        flux_values = _column_values(lc, flux_name)
        if flux_values is None:
            continue
        file_unit = _column_unit_str(lc, flux_name)
        group_id = _photcal_id_for_flux(author, spec)
        photcal_groups[group_id] = _photcal_payload(author, spec, lc, file_unit)
        issued_columns.append(
            (flux_name, flux_values, UCD_FLUX, _issue_unit(file_unit), group_id)
        )
        if spec.flux_err_col:
            err_name = normalize_lc_column(spec.flux_err_col)
            err_values = _column_values(lc, err_name)
            if err_values is not None:
                issued_columns.append(
                    (
                        err_name,
                        err_values,
                        UCD_FLUX_ERROR,
                        _issue_unit(_column_unit_str(lc, err_name)),
                        group_id,
                    )
                )

    bkg = get_background_spec(author)
    if bkg is not None:
        bkg_name = normalize_lc_column(bkg.bkg_col)
        bkg_values = _column_values(lc, bkg_name)
        if bkg_values is not None:
            bkg_group = f"photcal_{bkg_name}"
            photcal_groups[bkg_group] = _passband_photcal()
            issued_columns.append(
                (
                    bkg_name,
                    bkg_values,
                    UCD_BACKGROUND,
                    _issue_unit(_column_unit_str(lc, bkg_name)),
                    bkg_group,
                )
            )
            if bkg.bkg_err_col:
                bkg_err_name = normalize_lc_column(bkg.bkg_err_col)
                bkg_err_values = _column_values(lc, bkg_err_name)
                if bkg_err_values is not None:
                    issued_columns.append(
                        (
                            bkg_err_name,
                            bkg_err_values,
                            UCD_BACKGROUND_ERROR,
                            _issue_unit(_column_unit_str(lc, bkg_err_name)),
                            bkg_group,
                        )
                    )
    return issued_columns, photcal_groups


def _declared_flux_column(lc) -> str | None:
    """Returns the archive column Lightkurve declares as target flux.

    Args:
        lc: Lightkurve light curve.

    Returns:
        str or None: Lowercase column name from ``FLUX_ORIGIN``, or ``None``
        when it is absent or names no column of the product.
    """
    meta = getattr(lc, "meta", None) or {}
    raw = meta.get("FLUX_ORIGIN")
    if raw is None:
        return None
    name = normalize_lc_column(raw)
    present = {normalize_lc_column(item) for item in _colnames(lc)}
    return name if name in present else None


def _has_finite(values: np.ndarray) -> bool:
    """Returns whether a numeric array holds at least one finite value.

    Args:
        values (numpy.ndarray): Column values.

    Returns:
        bool: True when a finite number exists; False for text or all-NaN.
    """
    if values.dtype.kind not in "fiu":
        return False
    return bool(np.isfinite(values.astype(float)).any())


def _issued_columns_unknown_author(lc):
    """Keeps every Lightkurve column; roles come from Lightkurve's declaration.

    The flux role goes to the column named in ``FLUX_ORIGIN``. The error role
    goes to Lightkurve's ``flux_err`` when it holds finite values. Background
    is recognised by registry name. Every other column is issued without UCD.

    Args:
        lc: Lightkurve light curve.

    Returns:
        tuple: ``(issued_columns, photcal_groups)``.
    """
    flux_name = _declared_flux_column(lc)
    issued_columns: list[tuple] = []
    photcal_groups: dict[str, dict] = {}
    flux_group = None
    if flux_name is not None:
        flux_group = f"photcal_{flux_name}"
        photcal_groups[flux_group] = _unknown_flux_photcal(
            _column_unit_str(lc, flux_name)
        )

    for raw_name in _colnames(lc):
        name = normalize_lc_column(raw_name)
        if name == "time":
            continue
        values = _column_values(lc, name)
        if values is None:
            continue
        file_unit = _column_unit_str(lc, name)
        unit = _issue_unit(file_unit)
        ucd, group_id = None, None
        bkg_role = background_role_for_name(name)
        if flux_name is not None and name == flux_name:
            is_mag = file_unit is not None and str(file_unit).strip().lower() == "mag"
            ucd, group_id = (UCD_MAG if is_mag else UCD_FLUX), flux_group
        elif (
            flux_name is not None
            and name == "flux_err"
            and _has_finite(values)
        ):
            is_mag = _is_mag_unit(_column_unit_str(lc, flux_name))
            ucd = UCD_MAG_ERROR if is_mag else UCD_FLUX_ERROR
            group_id = flux_group
        elif bkg_role == ROLE_BACKGROUND:
            ucd, group_id = UCD_BACKGROUND, f"photcal_{name}"
            photcal_groups[group_id] = _passband_photcal()
        elif bkg_role == ROLE_BACKGROUND_ERROR:
            ucd, group_id = UCD_BACKGROUND_ERROR, f"photcal_{name}"
            photcal_groups[group_id] = _passband_photcal()
        issued_columns.append((name, values, ucd, unit, group_id))
    return issued_columns, photcal_groups


def _is_mag_unit(unit: str | None) -> bool:
    """Returns whether a unit string is magnitudes.

    Args:
        unit (str, optional): Unit string.

    Returns:
        bool: True for ``mag``.
    """
    return unit is not None and str(unit).strip().lower() == "mag"


def _unknown_flux_photcal(unit: str | None) -> dict:
    """Builds PhotCal for the declared flux column of an unknown author.

    Args:
        unit (str, optional): Unit read from the product.

    Returns:
        dict: 20.44 pair for electron s-1 / counts s-1, else passband only.
    """
    if is_spoc_family_flux_unit(unit):
        return _instrument_electron_photcal()
    return _passband_photcal()


def _instrument_electron_photcal() -> dict:
    """Returns PhotCal 20.44 for SPOC-family electron s-1 flux.

    Args:
        None.

    Returns:
        dict: PhotCal fields for XML emission.
    """
    return {
        "filter_identifier": config.TESS_FILTER_IDENTIFIER,
        "wavelength_m": config.effective_wavelength_m(),
        "mag_sys": config.TESS_MAG_SYS,
        "zp_flux": config.TESS_ELECTRON_S_ZERO_POINT_FLUX,
        "zp_flux_unit": config.TESS_ELECTRON_S_ZERO_POINT_FLUX_UNIT,
        "zp_mag": config.TESS_ELECTRON_S_ZERO_POINT_REF_MAG,
    }


def _column_unit_str(lc, name: str) -> str | None:
    """Reads the unit string of one Lightkurve column.

    Args:
        lc: Lightkurve light curve.
        name (str): Column name.

    Returns:
        str or None: Unit string, or ``None`` when the column has no unit.
    """
    try:
        col = lc[name]
    except Exception:
        return None
    unit = getattr(col, "unit", None)
    if unit is None or str(unit) in {"", "None"}:
        return None
    return str(unit)


def _votable_xml(
    lc,
    *,
    issued_columns,
    photcal_groups,
    time_mjd,
    tic: int,
    sector: int,
    author: str,
    exptime: float,
    mast_pointer: dict[str, str] | None = None,
) -> bytes:
    """Serialises issued columns to a calibrated VOTable.

    Args:
        lc: Lightkurve light curve (headers and sky coordinates).
        issued_columns: Column tuples ``(name, values, ucd, unit, group_id)``.
        photcal_groups (dict): PhotCal GROUP payloads keyed by ID.
        time_mjd: MJD time array.
        tic (int): TESS Input Catalogue number.
        sector (int): TESS sector.
        author (str): Pipeline author.
        exptime (float): Cadence in seconds.
        mast_pointer (dict, optional): MAST FITS pointer written as TABLE PARAMs.

    Returns:
        bytes: VOTable XML.
    """
    n_rows = len(time_mjd)
    for name, values, _ucd, _unit, _gid in issued_columns:
        if len(values) != n_rows:
            raise ValueError(
                f"{config.DISPLAY_NAME}: column {name} length {len(values)} "
                f"does not match time length {n_rows}."
            )

    ET.register_namespace("", _NS)
    root = ET.Element(f"{{{_NS}}}VOTABLE", {"version": "1.3"})
    resource = ET.SubElement(root, f"{{{_NS}}}RESOURCE")
    timesys = ET.SubElement(resource, f"{{{_NS}}}TIMESYS")
    timesys.set("ID", _TIMESYS_ID)
    timesys.set("refposition", config.TESS_REFPOSITION)
    timesys.set("timescale", config.TESS_TIMESCALE)
    timesys.set("timeorigin", str(config.ISSUED_TIMEORIGIN))

    fieldrefs_by_group: dict[str, list[str]] = {}
    for name, _values, _ucd, _unit, group_id in issued_columns:
        if group_id is None:
            continue
        fieldrefs_by_group.setdefault(group_id, []).append(name)

    for group_id, payload in photcal_groups.items():
        group = ET.SubElement(resource, f"{{{_NS}}}GROUP")
        group.set("ID", group_id)
        group.set("name", "photcal")
        _param(
            group,
            "filterIdentifier",
            payload["filter_identifier"],
            utype=_UT_FILTER,
            arraysize="*",
        )
        _param(
            group,
            "effectiveWavelength",
            repr(float(payload["wavelength_m"])),
            utype=_UT_WAVE,
            unit="m",
            datatype="double",
        )
        _param(group, "magnitudeSystem", payload["mag_sys"], utype=_UT_SYS, arraysize="*")
        if payload.get("zp_flux") is not None:
            _param(
                group,
                "zeroPointFlux",
                repr(float(payload["zp_flux"])),
                utype=_UT_FLUX,
                unit=payload["zp_flux_unit"],
                datatype="double",
            )
        if payload.get("zp_mag") is not None:
            _param(
                group,
                "zeroPointReferenceMagnitude",
                repr(float(payload["zp_mag"])),
                utype=_UT_MAG,
                unit="mag",
                datatype="double",
            )
        for field_id in fieldrefs_by_group.get(group_id, []):
            fieldref = ET.SubElement(group, f"{{{_NS}}}FIELDref")
            fieldref.set("ref", field_id)

    table = ET.SubElement(resource, f"{{{_NS}}}TABLE")
    table.set("name", f"{config.format_tic_name(tic)} {author} sector {sector}")
    description = ET.SubElement(table, f"{{{_NS}}}DESCRIPTION")
    if is_known_author(author):
        issue_note = (
            "All registered flux and background columns that are present in the "
            "product are issued."
        )
    else:
        issue_note = (
            "Author is not in the reviewed registry; every product column is "
            "issued. Roles follow Lightkurve's FLUX_ORIGIN; see docs/providers/tess.md."
        )
    description.text = (
        f"TESS archive light curve {config.format_tic_name(tic)}, "
        f"sector {sector}, author {author}, cadence {exptime:g} s. {issue_note}"
    )
    _table_param(table, "facility_name", config.FACILITY_NAME)
    _table_param(table, "instrument_name", config.INSTRUMENT_NAME)
    _table_param(table, "tic", str(int(tic)), datatype="long")
    _table_param(table, "sector", str(int(sector)), datatype="int")
    _table_param(table, "author", str(author))
    _table_param(table, "exptime", repr(float(exptime)), datatype="double", unit="s")
    if mast_pointer is not None:
        _table_param(table, "mast_obs_collection", mast_pointer["obs_collection"])
        _table_param(table, "mast_obs_id", mast_pointer["obs_id"])
        _table_param(table, "mast_product_filename", mast_pointer["product_filename"])
    ra_val = _sky_coord_deg(getattr(lc, "ra", None))
    dec_val = _sky_coord_deg(getattr(lc, "dec", None))
    if ra_val is not None:
        _table_param(table, "ra", repr(ra_val), datatype="double", ucd="pos.eq.ra")
    if dec_val is not None:
        _table_param(table, "dec", repr(dec_val), datatype="double", ucd="pos.eq.dec")
    period, epoch_jd = _tars_ephemeris(lc, author)
    if period is not None:
        _table_param(
            table,
            "period",
            repr(period),
            datatype="double",
            unit="d",
            ucd="src.var;time.period",
        )
    if epoch_jd is not None:
        _table_param(
            table,
            "epoch",
            repr(epoch_jd),
            datatype="double",
            unit="d",
            ucd="time.epoch",
            ref=_TIMESYS_ID,
        )

    _field(
        table,
        "time",
        "double",
        ucd="time.epoch",
        unit="d",
        ref=_TIMESYS_ID,
        field_id="time",
    )
    for name, values, ucd, unit, group_id in issued_columns:
        datatype, arraysize = _votable_datatype(values)
        _field(
            table,
            name,
            datatype,
            arraysize=arraysize,
            ucd=ucd,
            unit=unit,
            ref=group_id,
            field_id=name,
        )

    data = ET.SubElement(table, f"{{{_NS}}}DATA")
    tabledata = ET.SubElement(data, f"{{{_NS}}}TABLEDATA")
    for i in range(n_rows):
        if not math.isfinite(float(time_mjd[i])):
            continue
        tr = ET.SubElement(tabledata, f"{{{_NS}}}TR")
        _td(tr, repr(float(time_mjd[i])))
        for _name, values, _ucd, _unit, _gid in issued_columns:
            _td(tr, _cell_text(values[i]))

    logger.info(
        "%s issued TIC=%s sector=%s author=%s n_rows=%s columns=%s",
        config.DISPLAY_NAME,
        tic,
        sector,
        author,
        n_rows,
        ["time"] + [item[0] for item in issued_columns],
    )
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _photcal_id_for_flux(author: str, spec) -> str:
    """Returns the PhotCal GROUP ID for one flux column.

    Args:
        author (str): Pipeline author.
        spec: Flux column specification.

    Returns:
        str: GROUP ``ID``.
    """
    return f"photcal_{normalize_lc_column(spec.flux_col)}"


def _photcal_payload(author: str, spec, lc, file_unit: str | None) -> dict:
    """Builds PhotCal parameters for one target-flux column.

    Args:
        author (str): Pipeline author.
        spec: Flux column specification.
        lc: Lightkurve light curve.
        file_unit (str, optional): Flux unit read from the product.

    Returns:
        dict: PhotCal fields for XML emission.
    """
    if author in config.SPOC_INSTRUMENT_ZP_AUTHORS and is_spoc_family_flux_unit(
        file_unit
    ):
        return {
            "filter_identifier": config.TESS_FILTER_IDENTIFIER,
            "wavelength_m": config.effective_wavelength_m(),
            "mag_sys": config.TESS_MAG_SYS,
            "zp_flux": config.TESS_ELECTRON_S_ZERO_POINT_FLUX,
            "zp_flux_unit": config.TESS_ELECTRON_S_ZERO_POINT_FLUX_UNIT,
            "zp_mag": config.TESS_ELECTRON_S_ZERO_POINT_REF_MAG,
        }
    if spec.zp_mag_source == ZP_MAG_TESSMAG:
        tessmag = _header_float(lc, "TESSMAG")
        if tessmag is not None:
            return {
                "filter_identifier": config.TESS_FILTER_IDENTIFIER,
                "wavelength_m": config.effective_wavelength_m(),
                "mag_sys": config.TESS_MAG_SYS,
                "zp_flux": 1.0,
                "zp_flux_unit": "",
                "zp_mag": tessmag,
            }
        return _passband_photcal()
    if spec.zp_mag_source == ZP_MAG_GAIAMAG:
        gaiamag = _header_float(lc, "GAIAMAG")
        if gaiamag is not None:
            return {
                "filter_identifier": config.TESS_FILTER_IDENTIFIER,
                "wavelength_m": config.effective_wavelength_m(),
                "mag_sys": config.TESS_MAG_SYS,
                "zp_flux": 1.0,
                "zp_flux_unit": "",
                "zp_mag": gaiamag,
            }
        return _passband_photcal()
    return _passband_photcal()


def _passband_photcal() -> dict:
    """Returns filter-only PhotCal without zero points.

    Returns:
        dict: Passband PhotCal fields.
    """
    return {
        "filter_identifier": config.TESS_FILTER_IDENTIFIER,
        "wavelength_m": config.effective_wavelength_m(),
        "mag_sys": config.TESS_MAG_SYS,
        "zp_flux": None,
        "zp_flux_unit": None,
        "zp_mag": None,
    }


def _colnames(lc) -> list[str]:
    """Lists column names on a Lightkurve-like object.

    Args:
        lc: Light curve.

    Returns:
        list[str]: Column names.
    """
    if hasattr(lc, "colnames"):
        return [str(name) for name in lc.colnames]
    if hasattr(lc, "columns"):
        return [str(name) for name in lc.columns]
    raise ValueError(f"{config.DISPLAY_NAME}: light curve has no column names.")


def _check_time_system(lc) -> None:
    """Verifies the Lightkurve time object is BTJD on the TDB scale.

    FITS time keywords are not used: they describe the raw file, which
    Lightkurve readers may convert (CDIPS stores BJD, read as BTJD).

    Args:
        lc: Light curve.

    Raises:
        ValueError: When Lightkurve reports another time format or scale.
    """
    time = getattr(lc, "time", None)
    fmt = getattr(time, "format", None)
    scale = getattr(time, "scale", None)
    if fmt is not None and str(fmt).lower() != "btjd":
        raise ValueError(f"{config.DISPLAY_NAME}: time format {fmt!r}, expected BTJD.")
    if scale is not None and str(scale).lower() != "tdb":
        raise ValueError(f"{config.DISPLAY_NAME}: time scale {scale!r}, expected TDB.")


def _time_btjd(lc) -> np.ndarray | None:
    """Reads Lightkurve TIME as BTJD.

    Args:
        lc: Light curve.

    Returns:
        numpy.ndarray or None: Time values.
    """
    time = getattr(lc, "time", None)
    if time is None:
        values = _column_values(lc, "time")
        return values
    raw = getattr(time, "value", time)
    return np.asarray(raw, dtype=float)


def _column_values(lc, name: str) -> np.ndarray | None:
    """Reads one column keeping its real dtype, or ``None`` when absent.

    Masked integer columns become float with NaN so the mask is not lost.

    Args:
        lc: Light curve.
        name (str): Lowercase column name.

    Returns:
        numpy.ndarray or None: Values (float, integer, boolean, or text).
    """
    names = {normalize_lc_column(item): item for item in _colnames(lc)}
    key = names.get(normalize_lc_column(name))
    if key is None:
        return None
    try:
        series = lc[key]
    except Exception:
        series = getattr(lc, key, None)
        if series is None:
            return None
    raw = getattr(series, "value", series)
    if np.ma.isMaskedArray(raw):
        if raw.dtype.kind == "f":
            return np.asarray(raw.filled(np.nan))
        if raw.dtype.kind in "iub" and np.ma.getmaskarray(raw).any():
            return np.asarray(raw.astype(float).filled(np.nan))
        return np.asarray(raw.data)
    return np.asarray(raw)


def _votable_datatype(values: np.ndarray) -> tuple[str, str | None]:
    """Maps a numpy dtype to a VOTable datatype and arraysize.

    Args:
        values (numpy.ndarray): Column values.

    Returns:
        tuple[str, str or None]: ``(datatype, arraysize)``.
    """
    kind = values.dtype.kind
    if kind == "f":
        return "double", None
    if kind in "iu":
        return "long", None
    if kind == "b":
        return "boolean", None
    return "char", "*"


def _header_float(lc, key: str) -> float | None:
    """Reads a finite float from Lightkurve ``meta``.

    Args:
        lc: Light curve.
        key (str): Header keyword.

    Returns:
        float or None: Parsed value.
    """
    meta = getattr(lc, "meta", None) or {}
    raw = meta.get(key)
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return value


def _tars_ephemeris(lc, author: str) -> tuple[float | None, float | None]:
    """Reads TARS ``PER1`` and ``TMIN1`` when present.

    Args:
        lc: Light curve.
        author (str): Pipeline author.

    Returns:
        tuple: ``(period_days, epoch_jd)``.
    """
    if str(author).upper() != config.TARS_AUTHOR:
        return None, None
    period = _header_float(lc, "PER1")
    tmin_btjd = _header_float(lc, "TMIN1")
    epoch_jd = None if tmin_btjd is None else tmin_btjd + config.TESS_BTJD_OFFSET
    return period, epoch_jd


def _sky_coord_deg(value) -> float | None:
    """Extracts degrees from a coordinate attribute.

    Args:
        value: Float or quantity.

    Returns:
        float or None: Degrees.
    """
    if value is None:
        return None
    raw = getattr(value, "value", value)
    try:
        number = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _cell_text(value) -> str:
    """Formats one cell: finite number, integer, boolean, text, or empty.

    Args:
        value: Array element.

    Returns:
        str: Cell text; empty for non-finite numbers.
    """
    if isinstance(value, (np.bool_, bool)):
        return "1" if value else "0"
    if isinstance(value, (np.integer, int)):
        return str(int(value))
    if isinstance(value, (str, bytes, np.str_, np.bytes_)):
        return value.decode("utf-8") if isinstance(value, bytes) else str(value)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return repr(number) if math.isfinite(number) else ""


def _td(row: ET.Element, text: str) -> None:
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
    datatype: str = "char",
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
    if datatype == "char":
        param.set("arraysize", "*")
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
        parent (xml.etree.ElementTree.Element): GROUP element.
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
    """
    field = ET.SubElement(table, f"{{{_NS}}}FIELD")
    field.set("name", name)
    field.set("datatype", datatype)
    if arraysize:
        field.set("arraysize", arraysize)
    if ucd:
        field.set("ucd", ucd)
    if unit:
        field.set("unit", unit)
    if ref:
        field.set("ref", ref)
    if field_id:
        field.set("ID", field_id)
