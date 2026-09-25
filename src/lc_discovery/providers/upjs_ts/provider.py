"""UPJŠ time-series TAP lightcurve provider."""

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
from lc_discovery.lc_key import decode_lc_key
from lc_discovery.providers.ogle_ocvs.fetch_accref import fetch_votable_bytes
from lc_discovery.shared.gaia_dr3_source_id import (
    format_gaia_source_name,
    parse_gaia_source_id,
    pick_gaia_archive_id_from_simbad,
)
from lc_discovery.tap.client import run_tap_sync_query
from lc_discovery.providers.upjs_ts import config
from lc_discovery.providers.upjs_ts.fetch_metadata import enrich_votable
from lc_discovery.providers.upjs_ts.resolve_target import resolve_upjs_target_name
from lc_discovery.providers.upjs_ts.ssa_catalog import map_ssa_table_to_catalog
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


class UpjsTsProvider(MissionLightcurveProvider):
    """UPJŠ time series via the ``upjs_ts.ts_ssa`` TAP table."""

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
        return 15.0

    def max_discovery_search_radius_deg(self) -> float:
        """Returns the maximum cone search radius for UPJŠ SSA TAP.

        Returns:
            float: Upper bound in degrees.
        """
        return config.MAX_DISCOVERY_SEARCH_RADIUS_DEG

    def pick_archive_id_from_simbad(
        self,
        simbad_result: SimbadResolveResult,
    ) -> MissionArchiveMatch | None:
        """Selects a Gaia DR3 ``ssa_targname`` label from Simbad cross-identifiers.

        Args:
            simbad_result (SimbadResolveResult): Shared Simbad resolve payload.

        Returns:
            MissionArchiveMatch or None: Gaia SSA target label when recognised.
        """
        match = pick_gaia_archive_id_from_simbad(simbad_result)
        if match is None:
            return None
        return MissionArchiveMatch(
            archive_id=match.archive_id,
            match_kind="gaia_ssa_targname",
            matched_label=match.matched_label,
        )

    def resolve_target_name(self, name: str) -> MissionArchiveMatch | None:
        """Resolves Simbad or VSX names via ``upjs_ts.objects`` before Simbad.

        Args:
            name (str): Raw Target field text from the UI.

        Returns:
            MissionArchiveMatch or None: UPJŠ archive match when recognised.
        """
        return resolve_upjs_target_name(name)

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
        """Queries ``upjs_ts.ts_ssa`` for plottable lightcurve products.

        Direct name lookup tries Gaia DR3 ``ssa_targname`` labels first. Archive
        id lookup accepts either a Gaia ``source_id`` (resolved to ``ssa_targname``)
        or a UPJŠ ``object_id`` string.

        Args:
            ra_deg (float, optional): ICRS right ascension in degrees.
            dec_deg (float, optional): ICRS declination in degrees.
            radius_arcsec (float, optional): Cone radius in arcseconds.
            object_name (str, optional): Gaia DR3 label or target text from the UI.
            archive_id (str, optional): Gaia ``source_id`` or UPJŠ ``object_id``.
            time_start_mjd (float, optional): Lower time limit in MJD.
            time_end_mjd (float, optional): Upper time limit in MJD.
            **mission_options: Reserved for future provider options.

        Returns:
            astropy.table.Table: Standardised catalog table (possibly empty).
        """
        ssa_targname = self._resolve_ssa_targname(
            archive_id=archive_id,
            object_name=object_name,
        )
        if ssa_targname is not None:
            return self._catalog_by_ssa_targname(
                ssa_targname,
                time_start_mjd=time_start_mjd,
                time_end_mjd=time_end_mjd,
            )

        object_id = self._resolve_object_id(archive_id=archive_id)
        if object_id is not None:
            return self._catalog_by_object_id(
                object_id,
                time_start_mjd=time_start_mjd,
                time_end_mjd=time_end_mjd,
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

    def _catalog_by_ssa_targname(
        self,
        ssa_targname: str,
        *,
        time_start_mjd: float | None,
        time_end_mjd: float | None,
    ) -> Table:
        """Runs a TAP SSA query on ``ssa_targname``.

        Args:
            ssa_targname (str): Indexed SSA target label.
            time_start_mjd (float, optional): Lower time limit in MJD.
            time_end_mjd (float, optional): Upper time limit in MJD.

        Returns:
            astropy.table.Table: Standardised catalog table (possibly empty).
        """
        adql = config.adql_catalog_by_ssa_targname(
            ssa_targname,
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

    def _catalog_by_object_id(
        self,
        object_id: str,
        *,
        time_start_mjd: float | None,
        time_end_mjd: float | None,
    ) -> Table:
        """Runs a TAP SSA query on ``object_id``.

        Args:
            object_id (str): UPJŠ archive object identifier.
            time_start_mjd (float, optional): Lower time limit in MJD.
            time_end_mjd (float, optional): Upper time limit in MJD.

        Returns:
            astropy.table.Table: Standardised catalog table (possibly empty).
        """
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

    @staticmethod
    def _resolve_ssa_targname(
        *,
        archive_id: str | None,
        object_name: str | None,
    ) -> str | None:
        """Casts archive or UI text to an SSA ``ssa_targname`` Gaia label when possible.

        Args:
            archive_id (str, optional): Gaia ``source_id`` from Simbad cross-match.
            object_name (str, optional): Gaia label or UI target text.

        Returns:
            str or None: Canonical ``Gaia DR3 …`` SSA target label.
        """
        for candidate in (object_name, archive_id):
            if candidate is None:
                continue
            source_id = parse_gaia_source_id(str(candidate))
            if source_id is not None:
                return format_gaia_source_name(source_id)
            text = str(candidate).strip()
            if text.lower().startswith("gaia dr3"):
                return text
        return None

    @staticmethod
    def _resolve_object_id(*, archive_id: str | None) -> str | None:
        """Returns a UPJŠ ``object_id`` when ``archive_id`` is not a Gaia label.

        Args:
            archive_id (str, optional): Provider-resolved archive identifier.

        Returns:
            str or None: UPJŠ object id string.
        """
        if archive_id is None:
            return None
        if parse_gaia_source_id(str(archive_id)) is not None:
            return None
        text = str(archive_id).strip()
        return text or None
