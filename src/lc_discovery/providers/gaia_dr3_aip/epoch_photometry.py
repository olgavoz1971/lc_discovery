"""Extract band lightcurves from Gaia AIP epoch-photometry TAP rows."""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from astropy import units as u
from astropy.table import Table

from lc_discovery.providers.gaia_dr3_aip import config
from lc_discovery.providers.gaia_dr3_aip.array_columns import parse_array_column
from lc_discovery.shared.gaia_epoch_mag_error import mag_error_from_flux_over_error

logger = logging.getLogger(__name__)

_SOURCE_ID_COLUMNS = ("source_id", "datalinkID")


def _row_source_id(row) -> int | None:
    """Reads ``source_id`` from a TAP row with AIP column naming variants.

    Args:
        row: Astropy table row.

    Returns:
        int or None: Gaia source id when present.
    """
    for column in _SOURCE_ID_COLUMNS:
        if column not in row.colnames:
            continue
        value = row[column]
        if value is None or value == "":
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def epoch_row_to_cache_dict(row) -> dict[str, Any]:
    """Serialises one ``gaiadr3.epoch_photometry`` row for prefetch storage.

    Args:
        row: Astropy table row from the epoch-photometry TAP query.

    Returns:
        dict: Plain Python lists keyed by epoch-photometry column names.

    Raises:
        ValueError: When ``source_id`` is missing from the row.
    """
    source_id = _row_source_id(row)
    if source_id is None:
        raise ValueError("Epoch photometry row is missing source_id.")

    payload: dict[str, Any] = {"source_id": source_id}
    for column in config.EPOCH_SELECT_COLUMNS:
        if column == "source_id":
            continue
        if column not in row.colnames:
            payload[column] = []
            continue
        payload[column] = parse_array_column(row[column])
    return payload


def cache_dict_from_tap_table(tap_table: Table) -> dict[int, dict[str, Any]]:
    """Indexes prefetched epoch-photometry rows by ``source_id``.

    Args:
        tap_table (astropy.table.Table): TAP epoch-photometry result table.

    Returns:
        dict[int, dict]: Mapping from source id to serialisable epoch payload.
    """
    indexed: dict[int, dict[str, Any]] = {}
    for row in tap_table:
        try:
            payload = epoch_row_to_cache_dict(row)
        except ValueError as exc:
            logger.warning("%s skipping epoch row: %s", config.DISPLAY_NAME, exc)
            continue
        indexed[int(payload["source_id"])] = payload
    return indexed


def mag_error_from_snr(snr_values: np.ndarray) -> np.ndarray:
    """Derives magnitude uncertainties from flux signal-to-noise ratios.

    Args:
        snr_values (numpy.ndarray): Flux-over-error values from Gaia epoch photometry.

    Returns:
        numpy.ndarray: Magnitude uncertainties in mag.
    """
    return mag_error_from_flux_over_error(snr_values)


def aip_time_to_mjd(time_values: np.ndarray) -> np.ndarray:
    """Converts AIP epoch-photometry day offsets to absolute MJD.

    Args:
        time_values (numpy.ndarray): Times relative to BJD 2010-01-01 in days.

    Returns:
        numpy.ndarray: Modified Julian Date values.
    """
    return np.asarray(time_values, dtype=float) + config.GAIA_AIP_TIME_EPOCH_MJD


def extract_band_lightcurve(
    epoch_payload: dict[str, Any],
    *,
    band_code: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Extracts one passband lightcurve from a prefetched epoch-photometry record.

    Args:
        epoch_payload (dict): Serialised epoch-photometry arrays.
        band_code (str): Gaia passband code (``G``, ``BP``, or ``RP``).

    Returns:
        tuple[numpy.ndarray, numpy.ndarray, numpy.ndarray]: ``(time_mjd, mag, mag_err)``.
    """
    band = config.band_spec_for_code(band_code)
    times = np.asarray(epoch_payload.get(band.time_column) or [], dtype=float)
    mags = np.asarray(epoch_payload.get(band.mag_column) or [], dtype=float)
    snr = np.asarray(epoch_payload.get(band.snr_column) or [], dtype=float)

    length = min(len(times), len(mags), len(snr) if len(snr) else len(times))
    if length == 0:
        return (
            np.array([], dtype=float),
            np.array([], dtype=float),
            np.array([], dtype=float),
        )

    times = times[:length]
    mags = mags[:length]
    if len(snr):
        snr = snr[:length]
        mag_err = mag_error_from_snr(snr)
    else:
        mag_err = np.full(length, np.nan, dtype=float)

    time_mjd = aip_time_to_mjd(times)
    valid = np.isfinite(time_mjd) & np.isfinite(mags)
    return time_mjd[valid], mags[valid], mag_err[valid]


def band_time_bounds(
    epoch_payload: dict[str, Any],
    *,
    band_code: str,
) -> tuple[float | None, float | None]:
    """Computes catalogue ``t_min`` / ``t_max`` for one passband product.

    Args:
        epoch_payload (dict): Serialised epoch-photometry arrays.
        band_code (str): Gaia passband code.

    Returns:
        tuple[float or None, float or None]: MJD coverage bounds for valid epochs.
    """
    time_mjd, _, _ = extract_band_lightcurve(epoch_payload, band_code=band_code)
    if len(time_mjd) == 0:
        return None, None
    return float(np.min(time_mjd)), float(np.max(time_mjd))


def band_point_count(epoch_payload: dict[str, Any], *, band_code: str) -> int:
    """Counts valid photometry epochs for one passband product.

    Args:
        epoch_payload (dict): Serialised epoch-photometry arrays.
        band_code (str): Gaia passband code.

    Returns:
        int: Number of finite time/magnitude pairs.
    """
    time_mjd, mags, _ = extract_band_lightcurve(epoch_payload, band_code=band_code)
    return int(len(time_mjd))
