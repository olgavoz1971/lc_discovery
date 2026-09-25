"""Fixed Gaia DR3 debug catalogue for Lightcurve Discovery development.

Defines exactly three real Gaia DR3 sources used by the debug provider.
Coordinates, source identifiers, and mean magnitudes come from Gaia DR3
(queried once and frozen here). Epoch photometry is synthetic.

The debug provider exposes only Gaia ``source_id`` values in catalogue
``object_name`` fields — Gaia does not know Simbad or common-name labels.
"""

from __future__ import annotations

from dataclasses import dataclass

import lc_discovery.providers.gaia_debug.debug_config as gaia_config

# Literature / catalogue periods (days) for the And eclipsing binaries.
AA_AND_PERIOD_DAYS = 0.462436
AB_AND_PERIOD_DAYS = 0.33142


@dataclass(frozen=True)
class GaiaDr3DebugBandModel:
    """Synthetic epoch-photometry parameters for one Gaia passband."""

    mean_mag: float
    period_days: float | None
    amplitude_mag: float
    epoch_mjd: float
    noise_sigma_mag: float


@dataclass(frozen=True)
class GaiaDr3DebugSource:
    """One real Gaia DR3 source in the transparent debug micro-catalogue."""

    source_id: int
    ra_deg: float
    dec_deg: float
    t_min: float
    t_max: float
    lc_kind: str
    band_models: dict[str, GaiaDr3DebugBandModel]
    provider_note: str

    @property
    def catalogue_object_name(self) -> str:
        """Returns the Gaia DR3 designation used in catalogue ``object_name``.

        Returns:
            str: Standard Gaia DR3 source label (``Gaia DR3 <source_id>``).
        """
        return gaia_config.format_source_name(self.source_id)

    def mean_mag_for_band(self, band: str) -> float:
        """Returns the catalogue mean magnitude for a Gaia passband.

        Args:
            band (str): Gaia band code (``G``, ``BP``, or ``RP``).

        Returns:
            float: Mean magnitude stored for the band.
        """
        return self.band_models[gaia_config.normalise_band(band)].mean_mag

    def period_for_band(self, band: str) -> float | None:
        """Returns the declared period for a passband product, if periodic.

        Args:
            band (str): Gaia band code (``G``, ``BP``, or ``RP``).

        Returns:
            float or None: Period in days, or ``None`` for non-periodic products.
        """
        return self.band_models[gaia_config.normalise_band(band)].period_days


def _periodic_band_models(
    *,
    g_mag: float,
    bp_mag: float,
    rp_mag: float,
    g_period: float,
    bp_period: float,
    rp_period: float,
    epoch_mjd: float,
) -> dict[str, GaiaDr3DebugBandModel]:
    """Builds periodic sinusoid models for G, BP, and RP.

    Args:
        g_mag (float): Gaia DR3 ``phot_g_mean_mag``.
        bp_mag (float): Gaia DR3 ``phot_bp_mean_mag``.
        rp_mag (float): Gaia DR3 ``phot_rp_mean_mag``.
        g_period (float): Period in days for the G-band synthetic curve.
        bp_period (float): Period in days for the BP-band synthetic curve.
        rp_period (float): Period in days for the RP-band synthetic curve.
        epoch_mjd (float): Reference MJD for phase zero.

    Returns:
        dict: Band code to ``GaiaDr3DebugBandModel`` mapping.
    """
    return {
        gaia_config.GAIA_G_BAND: GaiaDr3DebugBandModel(
            mean_mag=g_mag,
            period_days=g_period,
            amplitude_mag=0.18,
            epoch_mjd=epoch_mjd,
            noise_sigma_mag=0.012,
        ),
        gaia_config.GAIA_BP_BAND: GaiaDr3DebugBandModel(
            mean_mag=bp_mag,
            period_days=bp_period,
            amplitude_mag=0.22,
            epoch_mjd=epoch_mjd,
            noise_sigma_mag=0.015,
        ),
        gaia_config.GAIA_RP_BAND: GaiaDr3DebugBandModel(
            mean_mag=rp_mag,
            period_days=rp_period,
            amplitude_mag=0.16,
            epoch_mjd=epoch_mjd,
            noise_sigma_mag=0.012,
        ),
    }


def _non_periodic_band_models(
    *,
    g_mag: float,
    bp_mag: float,
    rp_mag: float,
    epoch_mjd: float,
) -> dict[str, GaiaDr3DebugBandModel]:
    """Builds non-periodic synthetic models for G, BP, and RP.

    Args:
        g_mag (float): Gaia DR3 ``phot_g_mean_mag``.
        bp_mag (float): Gaia DR3 ``phot_bp_mean_mag``.
        rp_mag (float): Gaia DR3 ``phot_rp_mean_mag``.
        epoch_mjd (float): Reference MJD for the synthetic time series.

    Returns:
        dict: Band code to ``GaiaDr3DebugBandModel`` mapping.
    """
    return {
        gaia_config.GAIA_G_BAND: GaiaDr3DebugBandModel(
            mean_mag=g_mag,
            period_days=None,
            amplitude_mag=0.0,
            epoch_mjd=epoch_mjd,
            noise_sigma_mag=0.020,
        ),
        gaia_config.GAIA_BP_BAND: GaiaDr3DebugBandModel(
            mean_mag=bp_mag,
            period_days=None,
            amplitude_mag=0.0,
            epoch_mjd=epoch_mjd,
            noise_sigma_mag=0.025,
        ),
        gaia_config.GAIA_RP_BAND: GaiaDr3DebugBandModel(
            mean_mag=rp_mag,
            period_days=None,
            amplitude_mag=0.0,
            epoch_mjd=epoch_mjd,
            noise_sigma_mag=0.018,
        ),
    }


AA_AND = GaiaDr3DebugSource(
    source_id=1936512041221649536,
    ra_deg=346.3451680066482,
    dec_deg=47.676291847527416,
    t_min=57100.0,
    t_max=57180.0,
    lc_kind="periodic",
    band_models=_periodic_band_models(
        g_mag=10.811467,
        bp_mag=10.910253,
        rp_mag=10.606197,
        g_period=AA_AND_PERIOD_DAYS,
        bp_period=AA_AND_PERIOD_DAYS * 0.999,
        rp_period=AA_AND_PERIOD_DAYS * 1.001,
        epoch_mjd=57120.0,
    ),
    provider_note=(
        "Gaia DR3 debug source 1936512041221649536 - synthetic sinusoidal "
        "epoch photometry in G/BP/RP (periods declared per band)."
    ),
)

AB_AND = GaiaDr3DebugSource(
    source_id=1916588203329221632,
    ra_deg=347.88429175172206,
    dec_deg=36.892848148216316,
    t_min=57200.0,
    t_max=57280.0,
    lc_kind="periodic",
    band_models=_periodic_band_models(
        g_mag=9.713301,
        bp_mag=10.161166,
        rp_mag=9.074711,
        g_period=AB_AND_PERIOD_DAYS,
        bp_period=AB_AND_PERIOD_DAYS * 0.998,
        rp_period=AB_AND_PERIOD_DAYS * 1.002,
        epoch_mjd=57220.0,
    ),
    provider_note=(
        "Gaia DR3 debug source 1916588203329221632 - synthetic sinusoidal "
        "epoch photometry in G/BP/RP (periods declared per band)."
    ),
)

V433_AQL = GaiaDr3DebugSource(
    source_id=1807917937254374144,
    ra_deg=300.3148933444273,
    dec_deg=15.293278983562114,
    t_min=57300.0,
    t_max=57380.0,
    lc_kind="non_periodic",
    band_models=_non_periodic_band_models(
        g_mag=7.577562,
        bp_mag=9.762078,
        rp_mag=6.1803346,
        epoch_mjd=57320.0,
    ),
    provider_note=(
        "Gaia DR3 debug source 1807917937254374144 - synthetic non-periodic "
        "epoch photometry in G/BP/RP."
    ),
)

GAIA_DR3_DEBUG_SOURCES: tuple[GaiaDr3DebugSource, ...] = (AA_AND, AB_AND, V433_AQL)

_DEBUG_SOURCE_BY_ID = {source.source_id: source for source in GAIA_DR3_DEBUG_SOURCES}


def debug_source_by_id(source_id: int) -> GaiaDr3DebugSource | None:
    """Returns a debug-catalogue entry by Gaia DR3 ``source_id``.

    Args:
        source_id (int): Gaia DR3 source identifier.

    Returns:
        GaiaDr3DebugSource or None: Matching debug entry, if present.
    """
    return _DEBUG_SOURCE_BY_ID.get(int(source_id))


def all_debug_sources() -> tuple[GaiaDr3DebugSource, ...]:
    """Returns all entries in the Gaia DR3 debug micro-catalogue.

    Returns:
        tuple[GaiaDr3DebugSource, ...]: Frozen debug source records.
    """
    return GAIA_DR3_DEBUG_SOURCES
