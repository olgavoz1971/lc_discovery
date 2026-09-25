"""Gaia DR3 debug lightcurve provider for Lightcurve Discovery development.

This adapter exposes a fixed micro-catalogue of three real Gaia DR3 sources
with transparent synthetic epoch photometry for UI testing. Catalogue rows
use Gaia ``source_id`` labels only; common names are resolved via Simbad in
the Discovery orchestration layer, not by the Gaia provider.
"""

from __future__ import annotations

import io
import logging

import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.table import Table

from lc_discovery.base import (
    MissionArchiveMatch,
    MissionCapabilities,
    MissionLightcurveProvider,
)
from lc_discovery.catalog_schema import (
    empty_catalog_table,
    filter_catalog_table_by_time_bounds,
    validate_catalog_table,
)
from lc_discovery.shared.gaia_dr3_source_id import (
    format_gaia_source_name,
    parse_gaia_source_id,
)
from lc_discovery.lc_key import decode_lc_key, encode_lc_key
from skvo_veb.utils.lc_config import JD_TO_MJD
from skvo_veb.utils.my_tools import PipeException
from skvo_veb.utils.simbad_resolver import SimbadResolveResult
from volightcurve import VOLightCurve, write_vo_lightcurve

from . import debug_config as gaia_config
from .debug_catalog import (
    GaiaDr3DebugSource,
    all_debug_sources,
    debug_source_by_id,
)

logger = logging.getLogger(__name__)

_SYNTHETIC_EPOCH_POINTS = 48


def _resolve_debug_source(
    *,
    archive_id: str | None = None,
    object_name: str | None = None,
) -> GaiaDr3DebugSource | None:
    """Resolves a debug-catalogue entry from a Gaia ``source_id`` string only.

    Args:
        archive_id (str, optional): Gaia ``source_id`` string.
        object_name (str, optional): Gaia ``source_id`` string from the UI.

    Returns:
        GaiaDr3DebugSource or None: Matching debug entry, if present.
    """
    for candidate in (archive_id, object_name):
        if candidate is None:
            continue
        source_id = parse_gaia_source_id(str(candidate))
        if source_id is not None:
            return debug_source_by_id(source_id)
    return None


class GaiaDr3DebugProvider(MissionLightcurveProvider):
    """Gaia DR3 debug provider with a fixed three-source transparent catalogue."""

    mission_id = gaia_config.MISSION_ID
    display_name = "Gaia DR3 (debug)"
    export_profile = gaia_config.MISSION_ID
    capabilities = MissionCapabilities(
        supports_cone_search=True,
        supports_name_resolve=True,
        supports_id_lookup=True,
        supports_force_refresh=True,
        discovery_catalog_includes_n_points=True,
    )
    is_mock = True

    def default_search_radius_arcsec(self) -> float:
        """Returns the template default cone radius.

        Returns:
            float: Default search radius in arcseconds.
        """
        return 10.0

    def max_discovery_search_radius_deg(self) -> float:
        """Returns the maximum cone search radius for the debug micro-catalogue.

        Returns:
            float: Upper bound in degrees.
        """
        return gaia_config.MAX_DISCOVERY_SEARCH_RADIUS_DEG

    def pick_archive_id_from_simbad(self, simbad_result: SimbadResolveResult) -> MissionArchiveMatch | None:
        """Selects a Gaia DR3 source id from Simbad cross-identifiers.

        Only identifiers present in the debug micro-catalogue are accepted.

        Args:
            simbad_result (SimbadResolveResult): Shared Simbad resolve payload.

        Returns:
            MissionArchiveMatch or None: Gaia source id when present in the debug set.
        """
        for identifier in simbad_result.identifiers:
            source_id = parse_gaia_source_id(identifier)
            if source_id is None:
                continue
            if debug_source_by_id(source_id) is None:
                continue
            label = format_gaia_source_name(source_id)
            return MissionArchiveMatch(
                archive_id=str(source_id),
                match_kind="gaia_source_id",
                matched_label=label,
            )
        return None

    def resolve_target_name(self, name: str) -> MissionArchiveMatch | None:
        """Parses Gaia DR3 ``source_id`` strings before Simbad name resolution.

        Args:
            name (str): Raw Target field text from the UI.

        Returns:
            MissionArchiveMatch or None: Gaia archive match when recognised.
        """
        source_id = parse_gaia_source_id(name)
        if source_id is None or debug_source_by_id(source_id) is None:
            return None
        label = format_gaia_source_name(source_id)
        return MissionArchiveMatch(
            archive_id=str(source_id),
            match_kind="gaia_source_id",
            matched_label=label,
        )

    def search_catalog(
        self,
        *,
        ra_deg: float | None = None,
        dec_deg: float | None = None,
        radius_arcsec: float | None = None,
        object_name: str | None = None,
        archive_id: str | None = None,
        time_start_mjd: float | None = None,
        time_end_mjd: float | None = None,
        **mission_options,
    ) -> Table:
        """Returns debug Gaia DR3 SSA-style catalogue rows for cone or direct lookup.

        Args:
            ra_deg (float, optional): ICRS right ascension in degrees.
            dec_deg (float, optional): ICRS declination in degrees.
            radius_arcsec (float, optional): Cone radius in arcseconds.
            object_name (str, optional): Gaia ``source_id`` string.
            archive_id (str, optional): Gaia ``source_id`` for direct lookup.
            time_start_mjd (float, optional): Lower time limit in MJD.
            time_end_mjd (float, optional): Upper time limit in MJD.
            **mission_options: Reserved for future Gaia-specific filters.

        Returns:
            astropy.table.Table: Standardised catalog table (possibly empty).
        """
        debug_source = _resolve_debug_source(
            archive_id=archive_id,
            object_name=object_name,
        )
        if debug_source is not None:
            table = self._catalog_for_debug_source(debug_source, distance_arcsec=0.0)
            filtered = filter_catalog_table_by_time_bounds(
                table,
                time_start_mjd=time_start_mjd,
                time_end_mjd=time_end_mjd,
            )
            return self.finalize_discovery_catalog(filtered)

        if ra_deg is not None and dec_deg is not None and radius_arcsec is not None:
            table = self._catalog_cone(
                ra_deg=ra_deg,
                dec_deg=dec_deg,
                radius_arcsec=radius_arcsec,
            )
            return filter_catalog_table_by_time_bounds(
                table,
                time_start_mjd=time_start_mjd,
                time_end_mjd=time_end_mjd,
            )

        return empty_catalog_table()

    def _catalog_for_debug_source(
        self,
        debug_source: GaiaDr3DebugSource,
        *,
        distance_arcsec: float,
    ) -> Table:
        """Builds SSA/ObsCore rows for one debug-catalogue source.

        Args:
            debug_source (GaiaDr3DebugSource): Fixed debug source record.
            distance_arcsec (float): Separation from the search centre in arcseconds.

        Returns:
            astropy.table.Table: Three rows (G, BP, RP) or empty when invalid.
        """
        rows = self._ssa_products_for_source(
            debug_source=debug_source,
            distance_arcsec=distance_arcsec,
        )
        if not rows:
            return empty_catalog_table()
        return validate_catalog_table(Table(rows))

    def _catalog_cone(self, *, ra_deg: float, dec_deg: float, radius_arcsec: float) -> Table:
        """Returns debug SSA products within a cone around the supplied centre.

        Args:
            ra_deg (float): Cone centre right ascension in degrees.
            dec_deg (float): Cone centre declination in degrees.
            radius_arcsec (float): Cone radius in arcseconds.

        Returns:
            astropy.table.Table: Standardised catalog table (possibly empty).
        """
        ra, dec, radius = self._require_cone_search(
            ra_deg=ra_deg,
            dec_deg=dec_deg,
            radius_arcsec=radius_arcsec,
        )
        centre = SkyCoord(ra=ra * u.deg, dec=dec * u.deg, frame="icrs")
        rows: list[dict] = []
        for debug_source in all_debug_sources():
            source_coord = SkyCoord(
                ra=debug_source.ra_deg * u.deg,
                dec=debug_source.dec_deg * u.deg,
                frame="icrs",
            )
            separation = centre.separation(source_coord).to_value(u.arcsec)
            if separation > radius:
                continue
            rows.extend(
                self._ssa_products_for_source(
                    debug_source=debug_source,
                    distance_arcsec=separation,
                )
            )
        if not rows:
            return empty_catalog_table()
        table = validate_catalog_table(Table(rows))
        query_row_count = len(table)
        truncated = self._truncate_catalog_table(table)
        return self.finalize_discovery_catalog(
            truncated,
            cone_query_row_count=query_row_count,
        )

    def _ssa_products_for_source(
        self,
        *,
        debug_source: GaiaDr3DebugSource,
        distance_arcsec: float,
    ) -> list[dict]:
        """Splits one debug source into Gaia SSA/ObsCore catalogue products.

        Args:
            debug_source (GaiaDr3DebugSource): Fixed debug source record.
            distance_arcsec (float): Separation from search centre in arcseconds.

        Returns:
            list[dict]: One standardised row dict per Gaia passband product.
        """
        return [
            self._build_catalog_row(
                debug_source=debug_source,
                band=band,
                distance_arcsec=distance_arcsec,
            )
            for band in gaia_config.GAIA_MOCK_BANDS
        ]

    def _build_catalog_row(
        self,
        *,
        debug_source: GaiaDr3DebugSource,
        band: str,
        distance_arcsec: float,
    ) -> dict:
        """Builds one standardised SSA catalogue row dict for a debug source.

        Args:
            debug_source (GaiaDr3DebugSource): Fixed debug source record.
            band (str): Gaia passband code (``G``, ``BP``, ``RP``).
            distance_arcsec (float): Separation from search centre in arcseconds.

        Returns:
            dict: Row payload matching the shared catalogue schema.
        """
        band = gaia_config.normalise_band(band)
        band_model = debug_source.band_models[band]
        source_id = debug_source.source_id
        lc_key = encode_lc_key(
            self.mission_id,
            {
                "source_id": source_id,
                "band": band,
                "ra_deg": debug_source.ra_deg,
                "dec_deg": debug_source.dec_deg,
            },
        )
        row = {
            "distance_arcsec": distance_arcsec,
            "ra_deg": debug_source.ra_deg,
            "dec_deg": debug_source.dec_deg,
            "object_name": debug_source.catalogue_object_name,
            "filter_name": gaia_config.filter_name_for_band(band),
            "lc_key": lc_key,
            "t_min": debug_source.t_min,
            "t_max": debug_source.t_max,
            "filter_identifier": gaia_config.filter_identifier_for_band(band),
            "n_points": _SYNTHETIC_EPOCH_POINTS,
            "mag": band_model.mean_mag,
            "survey": gaia_config.GAIA_SURVEY,
            "provider_note": debug_source.provider_note,
            "epoch": band_model.epoch_mjd + JD_TO_MJD,
        }
        if band_model.period_days is not None:
            row["period"] = band_model.period_days
        return row

    def fetch_lightcurve(
        self,
        lc_key: str,
        *,
        force_refresh: bool = False,
        discovery_context=None,
    ) -> VOLightCurve:
        """Builds synthetic Gaia passband epoch photometry for a debug ``lc_key``.

        Args:
            lc_key (str): Serialised fetch handle from a catalog row.
            force_refresh (bool): Accepted for API compatibility; data are deterministic.

        Returns:
            VOLightCurve: VO-standard lightcurve parsed from generated VOTable bytes.

        Raises:
            PipeException: When the key is invalid or refers to a non-debug source.
        """
        if not self.validate_lc_key(lc_key):
            raise PipeException(f"{self.display_name}: invalid lightcurve key.")

        document = decode_lc_key(lc_key)
        payload = document["payload"]
        source_id = payload.get("source_id")
        band = payload.get("band", gaia_config.GAIA_G_BAND)
        ra_deg = payload.get("ra_deg", 0.0)
        dec_deg = payload.get("dec_deg", 0.0)
        if source_id is None:
            raise PipeException(f"{self.display_name}: lc_key payload missing source_id.")

        debug_source = debug_source_by_id(int(source_id))
        if debug_source is None:
            raise PipeException(
                f"{self.display_name}: source_id {source_id} is not in the debug catalogue."
            )

        table = _build_synthetic_epoch_table(debug_source, band=str(band))
        band_model = debug_source.band_models[gaia_config.normalise_band(band)]
        buffer = io.BytesIO()
        write_vo_lightcurve(
            buffer,
            table,
            **gaia_config.build_fetch_votable_kwargs(
                source_id=source_id,
                ra_deg=ra_deg,
                dec_deg=dec_deg,
                band=band,
                epoch=band_model.epoch_mjd,
            ),
        )
        buffer.seek(0)
        volc = VOLightCurve(buffer)
        volc.table.meta["facility_name"] = gaia_config.FACILITY_NAME
        volc.table.meta["instrument_name"] = gaia_config.INSTRUMENT_NAME
        logger.info(
            "%s fetch source_id=%s band=%s n_points=%s force_refresh=%s",
            self.display_name,
            source_id,
            band,
            len(volc),
            force_refresh,
        )
        from lc_discovery.shared.photcal_error_link import (
            share_photcal_with_unlinked_errors,
        )

        share_photcal_with_unlinked_errors(volc)
        return volc


def _build_synthetic_epoch_table(debug_source: GaiaDr3DebugSource, *, band: str) -> Table:
    """Creates transparent synthetic Gaia epoch photometry for one debug product.

    Args:
        debug_source (GaiaDr3DebugSource): Fixed debug source record.
        band (str): Gaia passband code.

    Returns:
        astropy.table.Table: Table with ``obs_time``, ``phot``, and ``flux_error``.
    """
    band_code = gaia_config.normalise_band(band)
    band_model = debug_source.band_models[band_code]
    seed = (debug_source.source_id % (2**32)) + hash(band_code) % (2**16)
    rng = np.random.default_rng(seed)

    obs_time = np.linspace(
        debug_source.t_min,
        debug_source.t_max,
        _SYNTHETIC_EPOCH_POINTS,
    )

    if band_model.period_days is not None:
        phase = 2.0 * np.pi * (obs_time - band_model.epoch_mjd) / band_model.period_days
        phot = band_model.mean_mag + band_model.amplitude_mag * np.sin(phase)
        phot += rng.normal(0.0, band_model.noise_sigma_mag, _SYNTHETIC_EPOCH_POINTS)
    else:
        span = float(obs_time[-1] - obs_time[0]) or 1.0
        centred = (obs_time - float(obs_time[0])) / span
        drift = 0.10 * (centred - 0.5)
        red_noise = np.cumsum(rng.normal(0.0, 0.012, _SYNTHETIC_EPOCH_POINTS))
        red_noise -= np.mean(red_noise)
        phot = band_model.mean_mag + drift + red_noise
        phot += rng.normal(0.0, band_model.noise_sigma_mag, _SYNTHETIC_EPOCH_POINTS)

    flux_error = np.clip(
        rng.normal(band_model.noise_sigma_mag, 0.004, _SYNTHETIC_EPOCH_POINTS),
        0.005,
        None,
    )

    table = Table()
    table["obs_time"] = obs_time
    table["phot"] = phot
    table["flux_error"] = flux_error
    table.meta["time_unit_note"] = f"MJD with origin {JD_TO_MJD}"
    table.meta["synthetic_model"] = debug_source.lc_kind
    if band_model.period_days is not None:
        table.meta["period_days"] = band_model.period_days
    return table


# Backward-compatible alias used in tests and docs.
GaiaDr3Provider = GaiaDr3DebugProvider
