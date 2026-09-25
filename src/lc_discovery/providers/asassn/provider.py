"""ASAS-SN Sky Patrol lightcurve provider."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from astropy.table import Table

from lc_discovery.providers.asassn import config
from lc_discovery.providers.asassn.catalog import map_metadata_table_to_catalog
from lc_discovery.providers.asassn.fetch_metadata import votable_from_band_table
from lc_discovery.providers.asassn.skypatrol_fetch import (
    fetch_discovery_by_asas_sn_id,
    fetch_discovery_by_gaia_id,
    fetch_discovery_by_simbad_name,
    fetch_discovery_cone,
    fetch_epoch_period_for_asas_sn_id,
    fetch_photometry_by_asas_sn_id,
    slice_band_photometry,
)
from lc_discovery.base import (
    MissionArchiveMatch,
    MissionCapabilities,
    MissionLightcurveProvider,
)
from lc_discovery.catalog_schema import empty_catalog_table
from lc_discovery.lc_key import decode_lc_key
from lc_discovery.shared.gaia_dr3_source_id import (
    format_gaia_source_name,
    parse_gaia_source_id,
    pick_gaia_archive_id_from_simbad,
)
from lc_discovery.simbad import SimbadResolveResult

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


class AsassnProvider(MissionLightcurveProvider):
    """ASAS-SN epoch photometry via the Sky Patrol client (no provider-side cache)."""

    mission_id = config.PROVIDER_ID
    display_name = config.DISPLAY_NAME
    export_profile = config.EXPORT_PROFILE
    capabilities = MissionCapabilities(
        supports_cone_search=True,
        supports_name_resolve=True,
        supports_id_lookup=True,
        supports_force_refresh=True,
        provides_catalog_epoch_period=False,
        supports_discovery_time_filter=False,
    )
    is_mock = False

    def default_search_radius_arcsec(self) -> float:
        """Returns the default cone radius for sky searches.

        Returns:
            float: Default search radius in arcseconds.
        """
        return 30.0

    def max_discovery_search_radius_deg(self) -> float:
        """Returns the maximum cone search radius for Sky Patrol discovery.

        Returns:
            float: Upper bound in degrees.
        """
        return config.MAX_DISCOVERY_SEARCH_RADIUS_DEG

    def discovery_cone_limit_entity_label(self) -> str:
        """Returns UI wording for cone truncation notices.

        Returns:
            str: Entity label for the discovery row cap.
        """
        return "ASAS-SN sources"

    def pick_archive_id_from_simbad(
        self,
        simbad_result: SimbadResolveResult,
    ) -> MissionArchiveMatch | None:
        """Selects Gaia DR3 ``source_id`` when present for ASAS-SN cross-match.

        Args:
            simbad_result (SimbadResolveResult): Shared Simbad resolve payload.

        Returns:
            MissionArchiveMatch or None: Gaia id match when recognised.
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
        """Queries Sky Patrol ``stellar_main`` metadata and expands candidate bands.

        Args:
            ra_deg (float, optional): ICRS right ascension in degrees.
            dec_deg (float, optional): ICRS declination in degrees.
            radius_arcsec (float, optional): Cone radius in arcseconds.
            object_name (str, optional): Gaia id or target name from the UI.
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

        gaia_id = self._resolve_gaia_id(archive_id=archive_id, object_name=object_name)
        if gaia_id is not None:
            metadata = fetch_discovery_by_gaia_id(gaia_id)
        elif object_name and str(object_name).strip() and archive_id is None:
            metadata = fetch_discovery_by_simbad_name(str(object_name).strip())
        elif ra_deg is not None and dec_deg is not None and radius_arcsec is not None:
            ra, dec, radius = self._require_cone_search(
                ra_deg=ra_deg,
                dec_deg=dec_deg,
                radius_arcsec=radius_arcsec,
            )
            centre_ra, centre_dec = ra, dec
            metadata = fetch_discovery_cone(
                ra_deg=ra,
                dec_deg=dec,
                radius_arcsec=radius,
            )
            limit = self.discovery_cone_query_row_limit()
            source_count = len(metadata)
            if source_count > limit:
                metadata = metadata.iloc[:limit].copy()
            cone_query_row_count = source_count
        else:
            return empty_catalog_table()

        if len(metadata) == 0:
            return empty_catalog_table()

        catalog = map_metadata_table_to_catalog(
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
        discovery_context=None,
    ) -> bytes:
        """Downloads one candidate band for an ASAS-SN ``asas_sn_id``.

        Args:
            lc_key (str): Serialised fetch handle from a catalogue row.
            force_refresh (bool): Accepted for API compatibility; always remote fetch.

        Returns:
            bytes: Calibrated VOTable for that band.

        Raises:
            ValueError: When the key is invalid or the band has no data.
        """
        if not self.validate_lc_key(lc_key):
            raise ValueError(f"{self.display_name}: invalid lightcurve key.")

        payload = decode_lc_key(lc_key)["payload"]
        asas_sn_id = payload.get("asas_sn_id")
        band = payload.get("band")
        if not asas_sn_id:
            raise ValueError(f"{self.display_name}: lc_key payload missing asas_sn_id.")
        if not band:
            raise ValueError(f"{self.display_name}: lc_key payload missing band.")

        logger.info(
            "%s fetch asas_sn_id=%s band=%s force_refresh=%s",
            self.display_name,
            asas_sn_id,
            band,
            force_refresh,
        )

        photometry = fetch_photometry_by_asas_sn_id(asas_sn_id)
        band_table = slice_band_photometry(
            photometry,
            band=str(band),
            asas_sn_id=asas_sn_id,
        )
        epoch_jd, period_days = fetch_epoch_period_for_asas_sn_id(asas_sn_id)

        meta_frame = fetch_discovery_by_asas_sn_id(asas_sn_id)
        ra_deg = dec_deg = None
        if len(meta_frame) > 0:
            try:
                ra_deg = float(meta_frame["ra_deg"].iloc[0])
                dec_deg = float(meta_frame["dec_deg"].iloc[0])
            except (TypeError, ValueError, KeyError):
                ra_deg = dec_deg = None

        payload = votable_from_band_table(
            band_table,
            asas_sn_id=asas_sn_id,
            band_code=str(band),
            ra_deg=ra_deg,
            dec_deg=dec_deg,
            epoch_jd=epoch_jd,
            period_days=period_days,
        )
        _save_debug_votable(payload)
        return payload

    @staticmethod
    def _resolve_gaia_id(
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
