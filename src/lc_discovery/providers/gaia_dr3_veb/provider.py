"""Gaia DR3 VEB TAP lightcurve provider (UPJS SSA + accref fetch)."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from astropy.table import Table

from lc_discovery.base import (
    MissionArchiveMatch,
    MissionCapabilities,
    MissionLightcurveProvider,
)
from lc_discovery.catalog_schema import empty_catalog_table
from lc_discovery.providers.gaia_dr3_veb import config
from lc_discovery.providers.gaia_dr3_veb.fetch_accref import fetch_votable_bytes
from lc_discovery.providers.gaia_dr3_veb.fetch_metadata import enrich_votable
from lc_discovery.providers.gaia_dr3_veb.ssa_catalog import map_ssa_table_to_catalog
from lc_discovery.shared.gaia_dr3_source_id import (
    format_gaia_source_name,
    parse_gaia_source_id,
    pick_gaia_archive_id_from_simbad,
)
from lc_discovery.lc_key import decode_lc_key
from lc_discovery.tap.client import run_tap_sync_query
from skvo_veb.utils.my_tools import PipeException
from skvo_veb.utils.simbad_resolver import SimbadResolveResult

logger = logging.getLogger(__name__)


def _save_debug_votable(payload: bytes) -> None:
    """Writes the enriched VOTable where it leaves this plugin.

    Files are ``lc_tmp_1.vot``, ``lc_tmp_2.vot``, and so on, in a temporary
    directory for this plugin only.

    Args:
        payload (bytes): Enriched VOTable.
    """
    folder = Path(tempfile.gettempdir()) / config.PROVIDER_ID
    folder.mkdir(parents=True, exist_ok=True)
    number = 1
    while (folder / f"lc_tmp_{number}.vot").exists():
        number += 1
    path = folder / f"lc_tmp_{number}.vot"
    path.write_bytes(payload)
    logger.info("%s debug VOTable %s", config.DISPLAY_NAME, path)


class GaiaDr3VebProvider(MissionLightcurveProvider):
    """Gaia DR3 epoch photometry via the UPJS VEB TAP SSA table"""

    mission_id = config.PROVIDER_ID
    display_name = config.DISPLAY_NAME
    export_profile = config.PROVIDER_ID
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
        return 2.0

    def max_discovery_search_radius_deg(self) -> float:
        """Returns the maximum cone search radius for UPJŠ Gaia SSA TAP.

        Returns:
            float: Upper bound in degrees.
        """
        return config.MAX_DISCOVERY_SEARCH_RADIUS_DEG

    def pick_archive_id_from_simbad(
        self,
        simbad_result: SimbadResolveResult,
    ) -> MissionArchiveMatch | None:
        """Selects a Gaia DR3 source id from Simbad cross-identifiers.

        Args:
            simbad_result (SimbadResolveResult): Shared Simbad resolve payload.

        Returns:
            MissionArchiveMatch or None: Gaia archive match when recognised.
        """
        return pick_gaia_archive_id_from_simbad(simbad_result)

    def resolve_target_name(self, name: str) -> MissionArchiveMatch | None:
        """Parses Gaia DR3 ``source_id`` strings before Simbad name resolution.

        Args:
            name (str): Raw Target field text from the UI.

        Returns:
            MissionArchiveMatch or None: Gaia archive match when recognised.
        """
        source_id = parse_gaia_source_id(name)
        if source_id is None:
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
        """Queries the VEB TAP SSA table for plottable Gaia DR3 products.

        Args:
            ra_deg (float, optional): ICRS right ascension in degrees.
            dec_deg (float, optional): ICRS declination in degrees.
            radius_arcsec (float, optional): Cone radius in arcseconds.
            object_name (str, optional): Gaia ``source_id`` string from the UI.
            archive_id (str, optional): Gaia ``source_id`` for direct lookup.
            time_start_mjd (float, optional): Lower time limit in MJD.
            time_end_mjd (float, optional): Upper time limit in MJD.
            **mission_options: Reserved for future provider options.

        Returns:
            astropy.table.Table: Standardised catalog table (possibly empty).
        """
        source_id = self._resolve_source_id(
            archive_id=archive_id,
            object_name=object_name,
        )

        if source_id is not None:
            adql = config.adql_catalog_by_source_id(
                source_id,
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
            bytes: Enriched VOTable. The Dash application parses it after this return.

        Raises:
            PipeException: When the key is invalid or download fails.
        """
        if not self.validate_lc_key(lc_key):
            raise PipeException(f"{self.display_name}: invalid lightcurve key.")

        payload = decode_lc_key(lc_key)["payload"]
        accref = payload.get("accref")
        if not accref:
            raise PipeException(f"{self.display_name}: lc_key payload missing accref.")

        logger.info(
            "%s fetch accref=%s force_refresh=%s",
            self.display_name,
            str(accref)[:64],
            force_refresh,
        )
        enriched = enrich_votable(fetch_votable_bytes(str(accref)))
        _save_debug_votable(enriched)
        return enriched

    @staticmethod
    def _resolve_source_id(
        *,
        archive_id: str | None,
        object_name: str | None,
    ) -> int | None:
        """Casts archive or UI text to a Gaia ``source_id`` when possible.

        Args:
            archive_id (str, optional): Mission-native archive id string.
            object_name (str, optional): Target field text.

        Returns:
            int or None: Parsed Gaia source id.
        """
        for candidate in (archive_id, object_name):
            if candidate is None:
                continue
            source_id = parse_gaia_source_id(str(candidate))
            if source_id is not None:
                return source_id
        return None
