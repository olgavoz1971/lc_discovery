"""Magnitude uncertainty for Gaia epoch photometry.

Pogson: ``σ_m = (2.5 / ln(10)) * (σ_F / F)``. For a flux-over-error ratio
the flux cancels, so ``σ_m = (2.5 / ln(10)) / SNR``.
"""

from __future__ import annotations

import numpy as np

_POGSON = 2.5 / np.log(10.0)


def mag_error_from_flux_over_error(snr_values) -> np.ndarray:
    """Derives magnitude uncertainties from flux signal-to-noise ratios.

    Args:
        snr_values: ``flux_over_error`` values (flux divided by flux error).

    Returns:
        numpy.ndarray: Magnitude uncertainties in mag. Non-positive or
        non-finite SNR entries are NaN.
    """
    snr = np.asarray(snr_values, dtype=float)
    mag_err = np.full_like(snr, np.nan, dtype=float)
    valid = np.isfinite(snr) & (snr > 0.0)
    mag_err[valid] = _POGSON / snr[valid]
    return mag_err
