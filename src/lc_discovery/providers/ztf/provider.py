"""ZTF DR24 IRSA lightcurve provider."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from astropy.table import Table

from lc_discovery.base import MissionArchiveMatch, MissionCapabilities, MissionLightcurveProvider
from lc_discovery.catalog_schema import empty_catalog_table
from lc_discovery.discovery_fetch_context import DiscoveryFetchContext
from lc_discovery.lc_key import decode_lc_key
from lc_discovery.providers.ztf import config
from lc_discovery.providers.ztf.catalog import (
    filter_discovery_frame_with_epochs,
    map_discovery_frame_to_catalog,
)
from lc_discovery.providers.ztf.fetch_metadata import votable_from_epochs
from lc_discovery.providers.ztf.oid import mission_archive_match_for_oid, parse_ztf_oid
from lc_discovery.providers.ztf.tap_discovery import query_objects_by_oid, query_objects_cone
from lc_discovery.providers.ztf.ztf_fetch import fetch_photometry_by_oid
from skvo_veb.utils.my_tools import PipeException

logger = logging.getLogger(__name__)


def _save_debug_votable(payload: bytes) -> None:
    """Writes the issued VOTable where it leaves this plugin.

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


class ZtfDr24Provider(MissionLightcurveProvider):
    """ZTF DR24 epoch photometry via IRSA TAP discovery and ``ztfquery`` fetch."""

    mission_id = config.PROVIDER_ID
    display_name = config.DISPLAY_NAME
    export_profile = config.EXPORT_PROFILE
    capabilities = MissionCapabilities(
        supports_cone_search=True,
        supports_name_resolve=False,
        supports_id_lookup=True,
        supports_force_refresh=True,
        provides_catalog_epoch_period=False,
        supports_discovery_time_filter=False,
        discovery_catalog_includes_n_points=True,
    )
    is_mock = False

    def default_search_radius_arcsec(self) -> float:
        """Returns the default cone radius for sky searches.

        Returns:
            float: Default search radius in arcseconds.
        """
        return 30.0

    def max_discovery_search_radius_deg(self) -> float:
        """Returns the maximum cone search radius for IRSA TAP discovery.

        Returns:
            float: Upper bound in degrees.
        """
        return config.MAX_DISCOVERY_SEARCH_RADIUS_DEG

    def discovery_cone_limit_entity_label(self) -> str:
        """Returns UI wording for cone truncation notices.

        Returns:
            str: Entity label for the discovery row cap.
        """
        return "ZTF lightcurve products"

    def resolve_target_name(self, name: str) -> MissionArchiveMatch | None:
        """Parses digit-only ZTF OID strings before Simbad name resolution.

        Args:
            name (str): Raw Target field text from the UI.

        Returns:
            MissionArchiveMatch or None: OID match when recognised.
        """
        oid = parse_ztf_oid(name)
        if oid is None:
            return None
        return mission_archive_match_for_oid(oid)

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
        """Queries IRSA ``ztf_objects_dr24`` and maps OID product rows.

        Args:
            ra_deg (float, optional): ICRS right ascension in degrees.
            dec_deg (float, optional): ICRS declination in degrees.
            radius_arcsec (float, optional): Cone radius in arcseconds.
            object_name (str, optional): Digit-only OID from the Target field.
            archive_id (str, optional): ZTF OID for direct lookup.
            time_start_mjd (float, optional): Ignored; unsupported for discovery.
            time_end_mjd (float, optional): Ignored; unsupported for discovery.
            **mission_options: Reserved for future provider options.

        Returns:
            astropy.table.Table: Standardised catalogue table (possibly empty).
        """
        centre_ra = ra_deg
        centre_dec = dec_deg
        cone_query_row_count: int | None = None

        oid = self._resolve_oid(archive_id=archive_id, object_name=object_name)
        if oid is not None:
            metadata = query_objects_by_oid(oid)
            centre_ra = centre_dec = None
        elif ra_deg is not None and dec_deg is not None and radius_arcsec is not None:
            ra, dec, radius = self._require_cone_search(
                ra_deg=ra_deg,
                dec_deg=dec_deg,
                radius_arcsec=radius_arcsec,
            )
            centre_ra, centre_dec = ra, dec
            metadata = query_objects_cone(ra_deg=ra, dec_deg=dec, radius_arcsec=radius)
        else:
            return empty_catalog_table()

        metadata = filter_discovery_frame_with_epochs(metadata)

        if (
            oid is None
            and ra_deg is not None
            and dec_deg is not None
            and radius_arcsec is not None
        ):
            limit = self.discovery_cone_query_row_limit()
            source_count = len(metadata)
            if source_count > limit:
                metadata = metadata.iloc[:limit].copy()
            cone_query_row_count = source_count

        if len(metadata) == 0:
            return empty_catalog_table()

        catalog = map_discovery_frame_to_catalog(
            metadata,
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
        """Downloads epoch photometry for one ZTF OID.

        Args:
            lc_key (str): Serialised fetch handle from a catalogue row.
            force_refresh (bool): Accepted for API compatibility; always remote fetch.
            discovery_context (DiscoveryFetchContext, optional): Discovery session
                metadata for lookup-aware titles.

        Returns:
            bytes: Calibrated VOTable for that OID.

        Raises:
            PipeException: When the key is invalid or fetch fails.
        """
        if not self.validate_lc_key(lc_key):
            raise PipeException(f"{self.display_name}: invalid lightcurve key.")

        payload = decode_lc_key(lc_key)["payload"]
        oid_raw = payload.get("oid")
        if not oid_raw:
            raise PipeException(f"{self.display_name}: lc_key payload missing oid.")

        fetch_quality = config.FETCH_QUALITY_RAW
        if discovery_context is not None:
            fetch_quality = str(discovery_context.fetch_quality or config.FETCH_QUALITY_RAW)

        logger.info(
            "%s fetch oid=%s force_refresh=%s quality=%s",
            self.display_name,
            oid_raw,
            force_refresh,
            fetch_quality,
        )

        meta_frame = query_objects_by_oid(oid_raw)
        filtercode = None
        ra_deg = dec_deg = None
        if len(meta_frame) > 0:
            row = meta_frame.iloc[0]
            filtercode = row.get("filtercode")
            try:
                ra_deg = float(row["ra"])
                dec_deg = float(row["dec"])
            except (TypeError, ValueError, KeyError):
                ra_deg = dec_deg = None

        if filtercode is None or str(filtercode).strip() == "":
            raise PipeException(
                f"{self.display_name}: cannot resolve filtercode for oid={oid_raw}."
            )

        epochs = fetch_photometry_by_oid(oid_raw, fetch_quality=fetch_quality)
        payload = votable_from_epochs(
            epochs,
            filtercode=str(filtercode),
            ra_deg=ra_deg,
            dec_deg=dec_deg,
        )
        _save_debug_votable(payload)
        return payload

    @staticmethod
    def _resolve_oid(
        *,
        archive_id: str | None,
        object_name: str | None,
    ) -> int | None:
        """Casts archive or UI text to a ZTF OID when possible.

        Args:
            archive_id (str, optional): Mission-native archive id string.
            object_name (str, optional): Target field text.

        Returns:
            int or None: Parsed ZTF OID.
        """
        for candidate in (archive_id, object_name):
            if candidate is None:
                continue
            parsed = parse_ztf_oid(str(candidate))
            if parsed is not None:
                return parsed
        return None
