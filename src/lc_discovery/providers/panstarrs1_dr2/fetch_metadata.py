"""Pan-STARRS1 DR2 detection table written as one calibrated VOTable."""

from __future__ import annotations

import io
import logging

import numpy as np
from astropy import units as u
from astropy.table import Table
from volightcurve import PhotCal, PhotDM, PhotometryFilter, write_vo_lightcurve

from lc_discovery.providers.panstarrs1_dr2 import config
from lc_discovery.providers.panstarrs1_dr2.mean_object_epoch import (
    coosys_epoch_year_from_detection_table,
)
from lc_discovery.providers.panstarrs1_dr2.ps1_names import format_ps1_object_name

logger = logging.getLogger(__name__)


def votable_from_detections(
    detection_table: Table,
    *,
    obj_id: int,
    filter_name: str,
    ra_deg: float,
    dec_deg: float,
) -> bytes:
    """Writes one Pan-STARRS1 filter as a calibrated VOTable, through ``volightcurve``.

    A row is removed when time or flux is missing. A missing flux error stays
    an empty cell. Flux numbers stay in Jy. The provider hands the core the table,
    the time system, the coordinate system and one calibration; the core writes the XML.

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
            raise ValueError(f"{config.DISPLAY_NAME}: detection table missing column {logical}.")
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
    out = Table()
    out["obs_time"] = np.array([row[0] for row in kept], dtype=float)
    out["obs_time"].unit = "d"
    out["obs_time"].info.meta = {"ucd": "time.epoch"}
    out["psf_flux"] = np.array([row[1] for row in kept], dtype=float)
    out["psf_flux"].unit = "Jy"
    out["psf_flux"].info.meta = {"ucd": "phot.flux;em.opt"}
    out["psf_flux_error"] = np.ma.masked_invalid(
        np.array([float(row[2]) if row[2] != "" else np.nan for row in kept], dtype=float)
    )
    out["psf_flux_error"].unit = "Jy"
    out["psf_flux_error"].info.meta = {"ucd": "stat.error;phot.flux"}

    photometry_filter = PhotometryFilter(
        filter_id=band.filter_identifier,
        spectral_location=(band.effective_wavelength_angstrom * u.AA).to(u.m),
    )
    calibration = PhotDM(
        photcal=PhotCal(
            zp_flux=config.AB_REFERENCE_FLUX_JY,
            zp_flux_unit="Jy",
            zp_mag=0.0,
            zp_mag_unit="mag",
            mag_sys=config.MAG_SYSTEM,
        ),
        photometry_filter=photometry_filter,
    )
    buffer = io.BytesIO()
    write_vo_lightcurve(
        buffer,
        out,
        f"{label} {band.filter_name}",
        refposition=config.REFPOSITION,
        timescale=config.TIMESCALE,
        timeorigin=config.TIMEORIGIN_MJD,
        table_description=description,
        ra=float(ra_deg),
        dec=float(dec_deg),
        binary=False,
        coosys_system=config.COOSYS_SYSTEM,
        coosys_epoch=coosys_epoch,
        publication_id=config.PUBLICATION_BIBCODE,
        facility_name=config.FACILITY_NAME,
        instrument_name=config.INSTRUMENT_NAME,
        photdms={"psf_flux": calibration, "psf_flux_error": calibration},
    )
    logger.info(
        "%s issued obj_id=%s filter=%s n_rows=%s",
        config.DISPLAY_NAME,
        obj_id,
        band.filter_name,
        len(kept),
    )
    return buffer.getvalue()


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
