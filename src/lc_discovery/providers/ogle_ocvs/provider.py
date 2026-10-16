"""OGLE OCVS TAP lightcurve provider (UPJS SSA + accref fetch)."""

from __future__ import annotations

import logging

from astropy.table import Table

from lc_discovery.base import (
    MissionArchiveMatch,
    MissionCapabilities,
    MissionLightcurveProvider,
)
from lc_discovery.catalog_schema import empty_catalog_table
from lc_discovery.shared import filter_spectral_coverage
from lc_discovery.coverage import ONGOING_MJD_END, WAVEBAND_OPTICAL, MissionCoverage
from lc_discovery.providers.ogle_ocvs import coverage_data
from lc_discovery.lc_key import decode_lc_key
from lc_discovery.providers.ogle_ocvs import config
from lc_discovery.providers.ogle_ocvs.fetch_accref import fetch_votable_bytes
from lc_discovery.providers.ogle_ocvs.fetch_metadata import enrich_votable
from lc_discovery.providers.ogle_ocvs.object_id import (
    normalize_ogle_object_id,
    pick_ogle_archive_id_from_simbad,
)
from lc_discovery.providers.ogle_ocvs.resolve_target import resolve_ogle_target_name
from lc_discovery.providers.ogle_ocvs.ssa_catalog import map_ssa_table_to_catalog
from lc_discovery.tap.client import run_tap_sync_query
from lc_discovery.simbad import SimbadResolveResult

logger = logging.getLogger(__name__)

class OgleOcvsProvider(MissionLightcurveProvider):
    """OGLE eclipsing variables via the UPJS ``ogle.ts_ssa`` TAP table."""

    mission_id = config.PROVIDER_ID
    display_name = config.DISPLAY_NAME
    export_profile = config.PROVIDER_ID
    description = (
      "OGLE Collection of Variable Stars (OCVS): a catalogue of variable stars "
      "discovered and classified by the Optical Gravitational Lensing Experiment, "
      "a long-running photometric survey using the 1.3 m Warsaw Telescope at "
      "Las Campanas Observatory, Chile.\n"
      "Where from: the UPJS TAP service (skvo.science.upjs.sk), which republishes "
      "the OCVS in our own archive.\n"
      "Bands: I and V. The I band carries the bulk of the epochs; V is sparser "
      "and mainly serves for colours.\n"
      "Time coverage: from 1992 to the present. The survey has run in phases "
      "(OGLE-I to OGLE-IV), and observations are ongoing with OGLE-IV (since 2010).\n"
      "Sky: the southern sky, mostly the Galactic bulge, parts of the Galactic "
      "disc, and the Large and Small Magellanic Clouds together with the "
      "Magellanic Bridge. Crowded, dense fields dominate; there is no all-sky coverage.\n"
      "Id lookup: OGLE object id (for example \"OGLE-LMC-RRLYR-13820\"); from Simbad "
      "take an identifier that contains \"OGLE\"; the plugin normalises its spelling.\n"
      "Reference: Udalski, Szymański & Szymański (2015), Acta Astronomica 65, 1 "
      "(OGLE-IV survey); individual OCVS catalogues are described in the "
      "papers by Soszyński et al. (variable-type specific)."
      "\nSearch row columns: distance_arcsec, ra_deg, dec_deg, object_name, filter_name and "
      "lc_key are always filled. Also filled: survey, provider_note (dataset title). Filled "
      "when the archive row has them: t_min and t_max (MJD), n_points, object_class, mag "
      "(mean magnitude). Empty: filter_identifier, period, epoch."
    )
    data_group = mission_id
    is_subset = False
    subset_description = ""
    group_rank = 1
    # Space: MOC supplied by the maintainer (the Registry record has no coverage), see
    # coverage_data.py. Time: from 1 January 1992 (MJD 48622), open end (the survey is
    # ongoing). Spectrum is unknown (None) until confirmed.
    coverage = MissionCoverage(
        spatial=coverage_data.OGLE_SPATIAL_MOC,
        temporal=((48622.0, ONGOING_MJD_END),),
        spectral=filter_spectral_coverage.OGLE_SPECTRAL,
        waveband=WAVEBAND_OPTICAL,
    )
    capabilities = MissionCapabilities(
        supports_cone_search=True,
        supports_name_resolve=True,
        supports_id_lookup=True,
        supports_force_refresh=True,
        discovery_catalog_includes_object_class=True,
        discovery_catalog_includes_n_points=True,
    )
    is_mock = False

    def default_search_radius_arcsec(self) -> float:
        """Returns the default cone radius for sky searches.

        Returns:
            float: Default search radius in arcseconds.
        """
        return 15.0

    def max_discovery_search_radius_deg(self) -> float:
        """Returns the maximum cone search radius for OGLE SSA TAP.

        Returns:
            float: Upper bound in degrees.
        """
        return config.MAX_DISCOVERY_SEARCH_RADIUS_DEG

    def pick_archive_id_from_simbad(
        self,
        simbad_result: SimbadResolveResult,
    ) -> MissionArchiveMatch | None:
        """Selects an OGLE ``object_id`` from Simbad cross-identifiers.

        Args:
            simbad_result (SimbadResolveResult): Shared Simbad resolve payload.

        Returns:
            MissionArchiveMatch or None: OGLE archive match when recognised.
        """
        return pick_ogle_archive_id_from_simbad(simbad_result)

    def resolve_target_name(self, name: str) -> MissionArchiveMatch | None:
        """Normalises loose OGLE spellings to ``object_id`` before Simbad.

        Args:
            name (str): Raw Target field text from the caller.

        Returns:
            MissionArchiveMatch or None: OGLE archive match when recognised.
        """
        return resolve_ogle_target_name(name)

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
        """Queries ``ogle.ts_ssa`` for plottable OGLE lightcurve products.

        Args:
            ra_deg (float, optional): ICRS right ascension in degrees.
            dec_deg (float, optional): ICRS declination in degrees.
            radius_arcsec (float, optional): Cone radius in arcseconds.
            object_name (str, optional): OGLE ``object_id`` or loose Simbad spelling.
            archive_id (str, optional): OGLE ``object_id`` for direct lookup.
            time_start_mjd (float, optional): Lower time limit in MJD.
            time_end_mjd (float, optional): Upper time limit in MJD.
            **mission_options: Reserved for future provider options.

        Returns:
            astropy.table.Table: Standardised catalog table (possibly empty).
        """
        object_id = self._resolve_object_id(
            archive_id=archive_id,
            object_name=object_name,
        )

        if object_id is not None:
            adql = config.adql_catalog_by_object_id(
                object_id,
                time_start_mjd=time_start_mjd,
                time_end_mjd=time_end_mjd,
            )
            tap_table = run_tap_sync_query(
                config.TAP_URL,
                adql,
                dialect=config.TAP_QUERY_DIALECT,
            )
            return map_ssa_table_to_catalog(
                tap_table,
                provider_id=self.mission_id,
            )

        if ra_deg is not None and dec_deg is not None and radius_arcsec is not None:
            ra, dec, radius = self._require_cone_search(
                ra_deg=ra_deg,
                dec_deg=dec_deg,
                radius_arcsec=radius_arcsec,
            )
            adql = config.adql_catalog_cone(
                ra_deg=ra,
                dec_deg=dec,
                radius_arcsec=radius,
                time_start_mjd=time_start_mjd,
                time_end_mjd=time_end_mjd,
                row_limit=self.max_discovery_catalog_rows(),
            )
            tap_table = run_tap_sync_query(
                config.TAP_URL,
                adql,
                dialect=config.TAP_QUERY_DIALECT,
            )
            catalog = map_ssa_table_to_catalog(
                tap_table,
                provider_id=self.mission_id,
                centre_ra_deg=ra,
                centre_dec_deg=dec,
            )
            return self.finalize_discovery_catalog(
                catalog,
                cone_query_row_count=len(tap_table),
            )

        return empty_catalog_table()

    def fetch_lightcurve(
        self,
        lc_key: str,
        *,
        force_refresh: bool = False,
        discovery_context=None,
    ) -> bytes:
        """Downloads one lightcurve and returns the enriched VOTable.

        Args:
            lc_key (str): Serialised fetch handle from a catalog row.
            force_refresh (bool): Accepted for API compatibility; no cache yet.

        Returns:
            bytes: Enriched VOTable. The caller parses it after this return.

        Raises:
            ValueError: When the key is invalid or download fails.
        """
        if not self.validate_lc_key(lc_key):
            raise ValueError(f"{self.display_name}: invalid lightcurve key.")

        payload = decode_lc_key(lc_key)["payload"]
        accref = payload.get("accref")
        if not accref:
            raise ValueError(f"{self.display_name}: lc_key payload missing accref.")

        logger.info(
            "%s fetch accref=%s force_refresh=%s",
            self.display_name,
            str(accref)[:64],
            force_refresh,
        )
        enriched = enrich_votable(fetch_votable_bytes(str(accref)))
        return enriched

    @staticmethod
    def _resolve_object_id(
        *,
        archive_id: str | None,
        object_name: str | None,
    ) -> str | None:
        """Normalises archive or caller text to an OGLE ``object_id`` when possible.

        Args:
            archive_id (str, optional): Mission-native archive id string.
            object_name (str, optional): Target field text.

        Returns:
            str or None: Canonical OGLE object id.
        """
        for candidate in (archive_id, object_name):
            if candidate is None:
                continue
            object_id = normalize_ogle_object_id(str(candidate))
            if object_id is not None:
                return object_id
        return None
