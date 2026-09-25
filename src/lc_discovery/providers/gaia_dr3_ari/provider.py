"""Gaia DR3 (ARI) TAP lightcurve provider."""

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
from lc_discovery.providers.gaia_dr3_ari import config
from lc_discovery.providers.gaia_dr3_ari.fetch_access_url import fetch_votable_bytes
from lc_discovery.providers.gaia_dr3_ari.fetch_metadata import enrich_votable
from lc_discovery.providers.gaia_dr3_ari.source_catalog import map_source_table_to_catalog
from lc_discovery.lc_key import decode_lc_key
from lc_discovery.shared.gaia_dr3_source_id import (
    format_gaia_source_name,
    parse_gaia_source_id,
    pick_gaia_archive_id_from_simbad,
)
from lc_discovery.tap.client import run_tap_sync_query
from lc_discovery.providers.gaia_dr3_ari.datalink import build_timeseries_datalink_url
from lc_discovery.simbad import SimbadResolveResult

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


class GaiaDr3AriProvider(MissionLightcurveProvider):
    """Gaia DR3 epoch photometry via Heidelberg ARI ``gaia_source`` discovery and timeseries datalink."""

    mission_id = config.PROVIDER_ID
    display_name = config.DISPLAY_NAME
    export_profile = config.PROVIDER_ID
    capabilities = MissionCapabilities(
        supports_cone_search=True,
        supports_name_resolve=True,
        supports_id_lookup=True,
        supports_force_refresh=True,
        provides_catalog_epoch_period=False,
        supports_discovery_time_filter=False,
        discovery_catalog_includes_object_class=True,
    )
    is_mock = False

    def default_search_radius_arcsec(self) -> float:
        """Returns the default cone radius for sky searches.

        Returns:
            float: Default search radius in arcseconds.
        """
        return 5.0

    def max_discovery_search_radius_deg(self) -> float:
        """Returns the maximum cone search radius for Heidelberg TAP discovery.

        Returns:
            float: Upper bound in degrees.
        """
        return config.MAX_DISCOVERY_SEARCH_RADIUS_DEG

    def pick_archive_id_from_simbad(
        self,
        simbad_result: SimbadResolveResult,
    ) -> MissionArchiveMatch | None:
        """Selects a Gaia DR3 ``source_id`` from Simbad cross-identifiers.

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
        """Queries ``gaiadr3.gaia_source`` with ``vari_classifier_result`` for discovery.

        Discovery runs one TAP query (cone or direct ``source_id``). Bundled epoch
        VOTables are fetched from the timeseries datalink when a row is loaded.

        Args:
            ra_deg (float, optional): ICRS right ascension in degrees.
            dec_deg (float, optional): ICRS declination in degrees.
            radius_arcsec (float, optional): Cone radius in arcseconds.
            object_name (str, optional): Gaia ``source_id`` string from the UI.
            archive_id (str, optional): Gaia ``source_id`` for direct lookup.
            time_start_mjd (float, optional): Ignored; time filtering is unsupported.
            time_end_mjd (float, optional): Ignored; time filtering is unsupported.
            **mission_options: Reserved for future provider options.

        Returns:
            astropy.table.Table: Standardised catalogue table (possibly empty).
        """
        centre_ra = ra_deg
        centre_dec = dec_deg
        cone_query_row_count: int | None = None

        source_id = self._resolve_source_id(
            archive_id=archive_id,
            object_name=object_name,
        )

        if source_id is not None:
            adql = config.adql_gaia_source_by_source_id(source_id)
            tap_table = run_tap_sync_query(
                config.TAP_URL,
                adql,
                dialect=config.TAP_QUERY_DIALECT,
            )
            return map_source_table_to_catalog(
                tap_table,
                provider_id=self.mission_id,
                centre_ra_deg=centre_ra,
                centre_dec_deg=centre_dec,
            )

        if ra_deg is not None and dec_deg is not None and radius_arcsec is not None:
            ra, dec, radius = self._require_cone_search(
                ra_deg=ra_deg,
                dec_deg=dec_deg,
                radius_arcsec=radius_arcsec,
            )
            centre_ra, centre_dec = ra, dec
            adql = config.adql_gaia_source_cone(
                ra_deg=ra,
                dec_deg=dec,
                radius_arcsec=radius,
                row_limit=self.max_discovery_catalog_rows(),
            )
            tap_table = run_tap_sync_query(
                config.TAP_URL,
                adql,
                dialect=config.TAP_QUERY_DIALECT,
            )
            cone_query_row_count = len(tap_table)
            catalog = map_source_table_to_catalog(
                tap_table,
                provider_id=self.mission_id,
                centre_ra_deg=ra,
                centre_dec_deg=dec,
            )
            return self.finalize_discovery_catalog(
                catalog,
                cone_query_row_count=cone_query_row_count,
            )

        return empty_catalog_table()

    def discovery_cone_limit_entity_label(self) -> str:
        """Returns UI wording for the Heidelberg cone ``TOP`` limit.

        Returns:
            str: Entity label for truncation notices.
        """
        return "Gaia sources"

    def fetch_lightcurve(
        self,
        lc_key: str,
        *,
        force_refresh: bool = False,
        discovery_context=None,
    ) -> bytes:
        """Downloads one band and returns the enriched VOTable.

        Args:
            lc_key (str): Serialised fetch handle from a catalog row.
            force_refresh (bool): Accepted for API compatibility; no cache yet.

        Returns:
            bytes: Enriched single-band VOTable. The Dash application parses it after this return.

        Raises:
            ValueError: When the key is invalid or download fails.
        """
        if not self.validate_lc_key(lc_key):
            raise ValueError(f"{self.display_name}: invalid lightcurve key.")

        payload = decode_lc_key(lc_key)["payload"]
        source_id = payload.get("source_id")
        access_url = payload.get("access_url")
        table_id = payload.get("table_id")
        if table_id is None:
            raise ValueError(f"{self.display_name}: lc_key payload missing table_id.")

        if source_id:
            url = build_timeseries_datalink_url(source_id)
        elif access_url:
            url = str(access_url)
        else:
            raise ValueError(f"{self.display_name}: lc_key payload missing source_id.")

        logger.info(
            "%s fetch url=%s table_id=%s force_refresh=%s",
            self.display_name,
            url[:64],
            table_id,
            force_refresh,
        )
        enriched = enrich_votable(fetch_votable_bytes(url), table_id=int(table_id))
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
            parsed = parse_gaia_source_id(str(candidate))
            if parsed is not None:
                return parsed
        return None
