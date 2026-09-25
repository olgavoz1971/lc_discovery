"""Magnitude uncertainty helpers for Gaia epoch photometry products.

Uses ``PhotCal.flux_err_to_mag_err`` (Pogson) — no local magnitude formula.
"""

from __future__ import annotations

import numpy as np
import astropy.units as u

from volightcurve import PhotCal

def _pogson_error_photcal() -> PhotCal:
    """Builds the arguments ``flux_err_to_mag_err`` needs for an SNR ratio.

    Pogson gives ``σ_m = (2.5/ln(10)) * (σ_F/F)``. The zero-point flux and
    the reference magnitude cancel, so the numbers below are not a Gaia
    catalogue calibration and are not written onto a light curve.

    Returns:
        PhotCal: Calibration used only inside this module.
    """
    return PhotCal(zp_flux=1.0, zp_mag=0.0)


MAG_ERR_FROM_SNR_FACTOR = float(
    _pogson_error_photcal().flux_err_to_mag_err(
        1.0 * u.dimensionless_unscaled,
        1.0 * u.dimensionless_unscaled,
    ).to_value(u.mag)
)


def mag_error_from_flux_over_error(snr_values) -> np.ndarray:
    """Derives magnitude uncertainties from flux signal-to-noise ratios.

    Uses Pogson error propagation on ``PhotCal``:
    ``σ_m = flux_err_to_mag_err(F, σ_F)`` with ``F=1``, ``σ_F=1/SNR``.

    Args:
        snr_values: ``flux_over_error`` values (flux divided by flux error).

    Returns:
        numpy.ndarray: Magnitude uncertainties in mag; invalid SNR entries are NaN.
    """
    snr = np.asarray(snr_values, dtype=float)
    mag_err = np.full_like(snr, np.nan, dtype=float)
    valid = np.isfinite(snr) & (snr > 0.0)
    if not np.any(valid):
        return mag_err
    n = int(np.count_nonzero(valid))
    flux = np.ones(n, dtype=float) * u.dimensionless_unscaled
    flux_err = (1.0 / snr[valid]) * u.dimensionless_unscaled
    result = _pogson_error_photcal().flux_err_to_mag_err(flux, flux_err)
    mag_err[valid] = np.asarray(result.to_value(u.mag), dtype=float)
    return mag_err
