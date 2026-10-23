"""Issue a calibrated VOTable for one TESS archive light curve."""

from __future__ import annotations

import io
import logging
import math

import numpy as np
import astropy.units as u
from astropy.table import Column, MaskedColumn, Table
from volightcurve import PhotCal, PhotDM, PhotometryFilter, write_vo_lightcurve

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


def _issue_unit(unit: str | None):
    """Returns the unit to write on an issued FIELD.

    Electron s-1 family units are written in the configured spelling. A unit that
    Astropy does not know, or that VOUnits cannot express, is kept as the archive wrote it.

    Args:
        unit (str, optional): Unit read from the product.

    Returns:
        astropy.units.UnitBase or None: Unit for the FIELD, or ``None``.
    """
    if unit is None:
        return None
    if is_spoc_family_flux_unit(unit):
        return u.UnrecognizedUnit(config.TESS_ELECTRON_S_ZERO_POINT_FLUX_UNIT)
    try:
        parsed = u.Unit(unit)
        parsed.to_string("vounit")
        return parsed
    except (ValueError, TypeError, u.UnitsError):
        logger.warning("%s unit %r is kept as written.", config.DISPLAY_NAME, unit)
        return u.UnrecognizedUnit(str(unit))


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
    """Writes the issued columns as a calibrated VOTable, through ``volightcurve``.

    A row whose time is not finite is not issued. A non-finite number in any other
    numeric column is issued as an empty (masked) cell.

    Args:
        lc: Lightkurve light curve (headers and sky coordinates).
        issued_columns: Column tuples ``(name, values, ucd, unit, group_id)``.
        photcal_groups (dict): PhotCal payloads keyed by group ID.
        time_mjd: MJD time array.
        tic (int): TESS Input Catalogue number.
        sector (int): TESS sector.
        author (str): Pipeline author.
        exptime (float): Cadence in seconds.
        mast_pointer (dict, optional): MAST FITS pointer written as TABLE PARAMs.

    Returns:
        bytes: VOTable XML.

    Raises:
        ValueError: When a column length differs from the time length.
    """
    n_rows = len(time_mjd)
    for name, values, _ucd, _unit, _gid in issued_columns:
        if len(values) != n_rows:
            raise ValueError(
                f"{config.DISPLAY_NAME}: column {name} length {len(values)} "
                f"does not match time length {n_rows}."
            )
    keep = np.isfinite(time_mjd)
    out = Table()
    out["time"] = Column(np.asarray(time_mjd, dtype=float)[keep], unit="d")
    out["time"].info.meta = {"ucd": "time.epoch"}
    for name, values, ucd, unit, _group_id in issued_columns:
        out[name] = _issued_column(values[keep], unit)
        if ucd:
            out[name].info.meta = {"ucd": ucd}

    photdm_by_group = {
        group_id: _photdm(payload) for group_id, payload in photcal_groups.items()
    }
    photdms = {
        name: photdm_by_group[group_id]
        for name, _values, ucd, _unit, group_id in issued_columns
        if group_id is not None and ucd and "phot." in ucd
    }

    description = (
        f"TESS archive light curve {config.format_tic_name(tic)}, "
        f"sector {sector}, author {author}, cadence {exptime:g} s. "
        + (
            "All registered flux and background columns that are present in the "
            "product are issued."
            if is_known_author(author)
            else "Author is not in the reviewed registry; every product column is "
            "issued. Roles follow Lightkurve's FLUX_ORIGIN; see docs/providers/tess.md."
        )
    )
    table_params = [
        {"name": "tic", "value": int(tic), "datatype": "long"},
        {"name": "sector", "value": int(sector), "datatype": "int"},
        {"name": "author", "value": str(author)},
        {"name": "exptime", "value": float(exptime), "datatype": "double", "unit": "s"},
    ]
    if mast_pointer is not None:
        table_params.extend(
            {"name": f"mast_{key}", "value": mast_pointer[key]}
            for key in ("obs_collection", "obs_id", "product_filename")
        )
    period, epoch_jd = _tars_ephemeris(lc, author)
    if period is not None:
        table_params.append(
            {
                "name": "period",
                "value": period,
                "datatype": "double",
                "unit": "d",
                "ucd": "src.var;time.period",
            }
        )
    if epoch_jd is not None:
        table_params.append(
            {
                "name": "epoch",
                "value": epoch_jd,
                "datatype": "double",
                "unit": "d",
                "ucd": "time.epoch",
                "ref": "ts",
            }
        )

    buffer = io.BytesIO()
    write_vo_lightcurve(
        buffer,
        out,
        f"{config.format_tic_name(tic)} {author} sector {sector}",
        refposition=config.TESS_REFPOSITION,
        timescale=config.TESS_TIMESCALE,
        timeorigin=config.ISSUED_TIMEORIGIN,
        table_description=description,
        ra=_sky_coord_deg(getattr(lc, "ra", None)),
        dec=_sky_coord_deg(getattr(lc, "dec", None)),
        binary=False,
        facility_name=config.FACILITY_NAME,
        instrument_name=config.INSTRUMENT_NAME,
        photdms=photdms,
        table_params=table_params,
    )
    logger.info(
        "%s issued TIC=%s sector=%s author=%s n_rows=%s columns=%s",
        config.DISPLAY_NAME,
        tic,
        sector,
        author,
        int(keep.sum()),
        list(out.colnames),
    )
    return buffer.getvalue()


def _photdm(payload: dict) -> PhotDM:
    """Builds the ``PhotDM`` of one PhotCal payload.

    Args:
        payload (dict): Output of the ``_photcal_payload`` family.

    Returns:
        volightcurve.PhotDM: Calibration; a zero point is declared only when given.
    """
    zp_flux = payload.get("zp_flux")
    zp_mag = payload.get("zp_mag")
    return PhotDM(
        photcal=PhotCal(
            zp_flux=zp_flux,
            zp_flux_unit=payload.get("zp_flux_unit") if zp_flux is not None else None,
            zp_mag=zp_mag,
            zp_mag_unit="mag" if zp_mag is not None else None,
            mag_sys=payload["mag_sys"],
        ),
        photometry_filter=PhotometryFilter(
            filter_id=payload["filter_identifier"],
            spectral_location=float(payload["wavelength_m"]) * u.m,
        ),
    )


def _issued_column(values: np.ndarray, unit) -> Column:
    """Builds one table column that keeps the archive datatype.

    Floats stay double and a non-finite value is masked; integers stay long;
    booleans stay boolean; anything else is text.

    Args:
        values (numpy.ndarray): Column values.
        unit (astropy.units.UnitBase or None): Column unit.

    Returns:
        astropy.table.Column: Plain or masked column.
    """
    kind = values.dtype.kind
    if kind == "f":
        data = np.asarray(values, dtype=float)
        return MaskedColumn(data, mask=~np.isfinite(data), unit=unit)
    if kind in "iu":
        return Column(np.asarray(values, dtype=np.int64), unit=unit)
    if kind == "b":
        return Column(np.asarray(values, dtype=bool), unit=unit)
    return Column(np.asarray([str(v) for v in values]), unit=unit)
