"""Pan-STARRS1 DR2 MAST TAP lightcurve provider."""

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
from lc_discovery.discovery_fetch_context import DiscoveryFetchContext
from lc_discovery.lc_key import decode_lc_key
from lc_discovery.providers.panstarrs1_dr2 import config
from lc_discovery.providers.panstarrs1_dr2.fetch_metadata import votable_from_detections
from lc_discovery.providers.panstarrs1_dr2.mean_object_catalog import map_mean_object_table_to_catalog
from lc_discovery.providers.panstarrs1_dr2.ps1_names import (
    mission_archive_match_for_obj_id,
    parse_ps1_obj_id,
)
from lc_discovery.providers.panstarrs1_dr2.tap_detection import fetch_detection_table
from lc_discovery.tap.client import run_tap_sync_query

logger = logging.getLogger(__name__)


def _save_debug_votable(payload: bytes) -> None:
    """Writes the issued VOTable where it leaves this plugin.

    Files are ``lc_tmp_1.vot``, ``lc_tmp_2.vot``, and so on, in a temporary
    directory for this plugin only.

    Args:
        payload (bytes): Issued VOTable.
    """
    folder = Path(tempfile.gettempdir()) / config.PROVIDER_ID
    folder.mkdir(parents=True, exist_ok=True)
    number = 1
    while (folder / f"lc_tmp_{number}.vot").exists():
        number += 1
    path = folder / f"lc_tmp_{number}.vot"
    path.write_bytes(payload)
    logger.info("%s debug VOTable %s", config.DISPLAY_NAME, path)


class Panstarrs1Dr2Provider(MissionLightcurveProvider):
    """Pan-STARRS1 DR2 epoch photometry via MAST TAP MeanObjectView and Detection."""

    mission_id = config.PROVIDER_ID
    display_name = config.DISPLAY_NAME
    export_profile = config.EXPORT_PROFILE
    capabilities = MissionCapabilities(
        supports_cone_search=True,
        supports_name_resolve=False,
        supports_id_lookup=True,
        supports_force_refresh=True,
        supports_discovery_time_filter=False,
        discovery_catalog_includes_n_points=True,
    )
    is_mock = False

    def default_search_radius_arcsec(self) -> float:
        """Returns the default cone radius for sky searches.

        Returns:
            float: Default search radius in arcseconds.
        """
        return 10.0

    def max_discovery_search_radius_deg(self) -> float:
        """Returns the maximum cone search radius.

        Returns:
            float: Upper bound in degrees.
        """
        return config.MAX_DISCOVERY_SEARCH_RADIUS_DEG

    def discovery_cone_limit_entity_label(self) -> str:
        """Returns UI wording for cone truncation notices.

        Returns:
            str: Entity label for the discovery row cap.
        """
        return "Pan-STARRS1 sources"

    def resolve_target_name(self, name: str) -> MissionArchiveMatch | None:
        """Parses numeric ``objID`` strings from the Target field.

        Args:
            name (str): Raw Target field text from the UI.

        Returns:
            MissionArchiveMatch or None: Mission-native match when recognised.
        """
        obj_id = parse_ps1_obj_id(name)
        if obj_id is None:
            return None
        return mission_archive_match_for_obj_id(obj_id)

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
        """Queries ``MeanObjectView`` and expands bands with at least one detection.

        Args:
            ra_deg (float, optional): ICRS right ascension in degrees.
            dec_deg (float, optional): ICRS declination in degrees.
            radius_arcsec (float, optional): Cone radius in arcseconds.
            object_name (str, optional): Numeric ``objID`` text from the UI.
            archive_id (str, optional): Numeric ``objID`` for direct lookup.
            time_start_mjd (float, optional): Ignored at discovery.
            time_end_mjd (float, optional): Ignored at discovery.
            **mission_options: Reserved for future provider options.

        Returns:
            astropy.table.Table: Standardised catalog table (possibly empty).
        """
        centre_ra = centre_dec = None
        cone_query_row_count: int | None = None
        adql: str | None = None

        for candidate in (object_name, archive_id):
            if candidate is None:
                continue
            text = str(candidate).strip()
            if not text:
                continue
            obj_id = parse_ps1_obj_id(text)
            if obj_id is not None:
                adql = config.adql_mean_object_by_obj_id(obj_id)
                break

        if adql is None and ra_deg is not None and dec_deg is not None and radius_arcsec is not None:
            ra, dec, radius = self._require_cone_search(
                ra_deg=ra_deg,
                dec_deg=dec_deg,
                radius_arcsec=radius_arcsec,
            )
            centre_ra, centre_dec = ra, dec
            adql = config.adql_mean_objects_cone(
                ra_deg=ra,
                dec_deg=dec,
                radius_arcsec=radius,
                row_limit=self.max_discovery_catalog_rows(),
            )

        if adql is None:
            return empty_catalog_table()

        tap_table = run_tap_sync_query(
            config.TAP_URL,
            adql,
            dialect=config.TAP_QUERY_DIALECT,
        )

        if centre_ra is not None:
            cone_query_row_count = len(tap_table)

        catalog = map_mean_object_table_to_catalog(
            tap_table,
            provider_id=self.mission_id,
            centre_ra_deg=centre_ra,
            centre_dec_deg=centre_dec,
        )
        return self.finalize_discovery_catalog(
            catalog,
            cone_query_row_count=cone_query_row_count,
        )

    def fetch_lightcurve(
        self,
        lc_key: str,
        *,
        force_refresh: bool = False,
        discovery_context: DiscoveryFetchContext | None = None,
    ) -> bytes:
        """Downloads detection epochs for one object and filter.

        Args:
            lc_key (str): Serialised fetch handle from a catalog row.
            force_refresh (bool): Accepted for API compatibility; always remote fetch.
            discovery_context (DiscoveryFetchContext, optional): Accepted for API compatibility.

        Returns:
            bytes: Calibrated VOTable for that filter.

        Raises:
            ValueError: When the key is invalid or fetch fails.
        """
        if not self.validate_lc_key(lc_key):
            raise ValueError(f"{self.display_name}: invalid lightcurve key.")

        payload = decode_lc_key(lc_key)["payload"]
        obj_id_raw = payload.get("obj_id")
        filter_name = payload.get("filter")
        if obj_id_raw is None or filter_name is None:
            raise ValueError(f"{self.display_name}: lc_key payload missing obj_id or filter.")

        try:
            obj_id = int(obj_id_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{self.display_name}: invalid obj_id in lc_key.") from exc

        ra_deg = float(payload["ra_deg"])
        dec_deg = float(payload["dec_deg"])

        logger.info(
            "%s fetch obj_id=%s filter=%s force_refresh=%s",
            self.display_name,
            obj_id,
            filter_name,
            force_refresh,
        )

        detection_table = fetch_detection_table(
            obj_id=obj_id,
            filter_name=str(filter_name),
        )
        payload = votable_from_detections(
            detection_table,
            obj_id=obj_id,
            filter_name=str(filter_name),
            ra_deg=ra_deg,
            dec_deg=dec_deg,
        )
        _save_debug_votable(payload)
        return payload
