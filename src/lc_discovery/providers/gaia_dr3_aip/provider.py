"""Gaia DR3 (AIP) TAP lightcurve provider."""

from __future__ import annotations

import logging

from astropy.table import Table

from lc_discovery.base import (
    MissionArchiveMatch,
    MissionCapabilities,
    MissionLightcurveProvider,
)
from lc_discovery.catalog_schema import empty_catalog_table
from lc_discovery.shared.gaia_dr3_coverage import GAIA_DR3_EPOCH_PHOTOMETRY_COVERAGE
from lc_discovery.providers.gaia_dr3_aip import config
from lc_discovery.providers.gaia_dr3_aip.fetch_metadata import votable_from_cached_epoch
from lc_discovery.providers.gaia_dr3_aip.catalog import map_source_table_to_catalog
from lc_discovery.providers.gaia_dr3_aip.epoch_photometry import cache_dict_from_tap_table
from lc_discovery.providers.gaia_dr3_aip.prefetch_store import (
    clear_epoch_photometry,
    epoch_photometry_is_cached,
    load_epoch_photometry,
    store_epoch_photometry,
)
from lc_discovery.lc_key import decode_lc_key
from lc_discovery.shared.gaia_dr3_source_id import (
    format_gaia_source_name,
    parse_gaia_source_id,
    pick_gaia_archive_id_from_simbad,
)
from lc_discovery.tap.client import run_tap_sync_query
from lc_discovery.simbad import SimbadResolveResult

logger = logging.getLogger(__name__)

class GaiaDr3AipProvider(MissionLightcurveProvider):
    """Gaia DR3 epoch photometry via the Gaia@AIP TAP ``epoch_photometry`` table."""

    mission_id = config.PROVIDER_ID
    display_name = config.DISPLAY_NAME
    export_profile = config.PROVIDER_ID
    description = (
      "Gaia DR3 epoch photometry: time series for the subset of sources that Gaia "
      "released with epoch data, mostly variable-star candidates.\n"
      "Where from: the Gaia@AIP TAP service (gaia.aip.de). Epoch photometry is "
      "fetched on first load of a source and kept on disk for all three bands.\n"
      "Bands: G, BP and RP.\n"
      "Time coverage: 25 July 2014 to 28 May 2017 (the DR3 observing period, "
      "about 34 months). \n" 
      "Sky: all sky, but only sources flagged as having epoch photometry. "
      "Sampling is irregular and follows the Gaia scanning law, so the number of "
      "epochs varies strongly with position on the sky.\n"
      "Id lookup: Gaia DR3 source_id (digits only); from Simbad take the identifier "
      "that starts with \"Gaia DR3 \".\n"
      "Reference: Gaia Collaboration, Vallenari et al. (2023), A&A 674, A1 "
      "(Gaia DR3 summary); Gaia Collaboration, Prusti et al. (2016), A&A 595, A1 "
      "(the mission)."
      "\nSearch row columns: distance_arcsec, ra_deg, dec_deg, object_name, filter_name and "
      "lc_key are always filled. Three rows per source (G, BP, RP). Also filled: "
      "filter_identifier, survey, provider_note, object_class (Gaia variability class), mag "
      "(mean G magnitude, on the G row only). Empty in a plain search: t_min, t_max, "
      "n_points, period, epoch; time coverage and epoch photometry are read at fetch."
    )
    data_group = "gaia_dr3_epoch_photometry"
    is_subset = False
    subset_description = ""
    group_rank = 2
    coverage = GAIA_DR3_EPOCH_PHOTOMETRY_COVERAGE
    capabilities = MissionCapabilities(
        supports_cone_search=True,
        supports_name_resolve=True,
        supports_id_lookup=True,
        supports_force_refresh=True,
        supports_cache_purge=True,
        provides_catalog_epoch_period=False,
        supports_discovery_time_filter=False,
        discovery_catalog_includes_object_class=True,
        discovery_catalog_includes_n_points=True,
    )
    is_mock = False

    def default_search_radius_arcsec(self) -> float:
        """Returns the default cone radius for sky searches.

        Returns:
            float: Default search radius in arcseconds.
        """
        return 5.0

    def max_discovery_search_radius_deg(self) -> float:
        """Returns the maximum cone search radius for Gaia@AIP TAP queries.

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
            name (str): Raw Target field text from the caller.

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
        """Queries Gaia@AIP ``gaia_source`` for discovery catalogue rows.

        Discovery runs a single TAP query (cone or direct ``source_id``) with an
        optional ``vari_classifier_result`` join. Epoch photometry is fetched when
        a row is loaded, not during catalogue search.

        Args:
            ra_deg (float, optional): ICRS right ascension in degrees.
            dec_deg (float, optional): ICRS declination in degrees.
            radius_arcsec (float, optional): Cone radius in arcseconds.
            object_name (str, optional): Gaia ``source_id`` string from the caller.
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
            source_table = self._query_gaia_source_by_id(source_id)
        elif ra_deg is not None and dec_deg is not None and radius_arcsec is not None:
            ra, dec, radius = self._require_cone_search(
                ra_deg=ra_deg,
                dec_deg=dec_deg,
                radius_arcsec=radius_arcsec,
            )
            centre_ra, centre_dec = ra, dec
            source_table = self._query_gaia_source_cone(
                ra_deg=ra,
                dec_deg=dec,
                radius_arcsec=radius,
            )
            cone_query_row_count = len(source_table)
        else:
            return empty_catalog_table()

        if len(source_table) == 0:
            return empty_catalog_table()

        catalog = map_source_table_to_catalog(
            source_table,
            provider_id=self.mission_id,
            centre_ra_deg=centre_ra,
            centre_dec_deg=centre_dec,
        )
        return self.finalize_discovery_catalog(
            catalog,
            cone_query_row_count=cone_query_row_count,
        )

    def discovery_cone_limit_entity_label(self) -> str:
        """Returns wording for the Gaia@AIP cone ``TOP`` limit.

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
        """Downloads epoch photometry and returns one band as a VOTable.

        Args:
            lc_key (str): Serialised fetch handle from a catalog row.
            force_refresh (bool): When true, delete the prefetched record and
                query epoch photometry from TAP again.

        Returns:
            bytes: Enriched VOTable. The caller parses it after this return.

        Raises:
            ValueError: When the key is invalid or fetch fails validation.
        """
        if not self.validate_lc_key(lc_key):
            raise ValueError(f"{self.display_name}: invalid lightcurve key.")

        payload = decode_lc_key(lc_key)["payload"]
        source_id = payload.get("source_id")
        band = payload.get("band")
        filter_name = payload.get("filter_name")
        ra_deg = payload.get("ra_deg")
        dec_deg = payload.get("dec_deg")
        if source_id is None:
            raise ValueError(f"{self.display_name}: lc_key payload missing source_id.")
        if not band:
            raise ValueError(f"{self.display_name}: lc_key payload missing band.")
        if not filter_name:
            raise ValueError(f"{self.display_name}: lc_key payload missing filter_name.")
        if ra_deg is None or dec_deg is None:
            raise ValueError(f"{self.display_name}: lc_key payload missing sky position.")

        if force_refresh:
            clear_epoch_photometry(source_id)
        if force_refresh or not epoch_photometry_is_cached(source_id):
            self._fetch_and_cache_epoch_photometry(int(source_id))

        logger.info(
            "%s fetch source_id=%s band=%s force_refresh=%s",
            self.display_name,
            source_id,
            band,
            force_refresh,
        )
        enriched = votable_from_cached_epoch(load_epoch_photometry(source_id), band_code=str(band))
        return enriched

    def purge_cached_product(self, lc_key: str) -> bool:
        """Deletes the prefetched epoch photometry of the key's source.

        The record holds all bands of one Gaia source, so the other bands of
        that source are fetched again too.

        Args:
            lc_key (str): Serialised fetch handle from a catalog row.

        Returns:
            bool: True when a record was deleted, False when none was cached.

        Raises:
            ValueError: When the key is invalid or has no ``source_id``.
        """
        if not self.validate_lc_key(lc_key):
            raise ValueError(f"{self.display_name}: invalid lightcurve key.")
        source_id = decode_lc_key(lc_key)["payload"].get("source_id")
        if source_id is None:
            raise ValueError(f"{self.display_name}: lc_key payload missing source_id.")
        return clear_epoch_photometry(source_id)

    def _query_gaia_source_by_id(self, source_id: int) -> Table:
        """Runs the Gaia source lookup ADQL query.

        Args:
            source_id (int): Gaia DR3 source identifier.

        Returns:
            astropy.table.Table: ``gaiadr3.gaia_source`` result table.
        """
        adql = config.adql_gaia_source_by_id(source_id)
        return run_tap_sync_query(
            config.TAP_URL,
            adql,
            dialect=config.TAP_QUERY_DIALECT,
        )

    def _query_gaia_source_cone(
        self,
        *,
        ra_deg: float,
        dec_deg: float,
        radius_arcsec: float,
    ) -> Table:
        """Runs the Gaia source cone-search ADQL query.

        Args:
            ra_deg (float): Cone centre right ascension in degrees.
            dec_deg (float): Cone centre declination in degrees.
            radius_arcsec (float): Cone radius in arcseconds.

        Returns:
            astropy.table.Table: ``gaiadr3.gaia_source`` result table.
        """
        adql = config.adql_gaia_source_cone(
            ra_deg=ra_deg,
            dec_deg=dec_deg,
            radius_arcsec=radius_arcsec,
            row_limit=self.max_discovery_catalog_rows(),
        )
        return run_tap_sync_query(
            config.TAP_URL,
            adql,
            dialect=config.TAP_QUERY_DIALECT,
        )

    def _query_epoch_photometry(self, source_ids: list[int]) -> Table:
        """Runs batched epoch-photometry ADQL queries for many sources.

        Args:
            source_ids (list[int]): Gaia DR3 source identifiers.

        Returns:
            astropy.table.Table: Combined ``gaiadr3.epoch_photometry`` result.
        """
        if not source_ids:
            return Table()

        chunks: list[Table] = []
        batch_size = config.MAX_SOURCE_IDS_PER_EPOCH_QUERY
        for start in range(0, len(source_ids), batch_size):
            batch = source_ids[start : start + batch_size]
            adql = config.adql_epoch_photometry_for_source_ids(batch)
            chunks.append(
                run_tap_sync_query(
                    config.TAP_URL,
                    adql,
                    dialect=config.TAP_QUERY_DIALECT,
                )
            )

        if len(chunks) == 1:
            return chunks[0]
        from astropy.table import vstack

        return vstack(chunks)

    def _fetch_and_cache_epoch_photometry(self, source_id: int) -> None:
        """Queries ``epoch_photometry`` for one source and stores it in the prefetch cache.

        Args:
            source_id (int): Gaia DR3 source identifier.

        Raises:
            ValueError: When TAP returns no epoch photometry for the source.
        """
        epoch_table = self._query_epoch_photometry([source_id])
        epoch_by_source = cache_dict_from_tap_table(epoch_table)
        epoch_payload = epoch_by_source.get(source_id)
        if epoch_payload is None:
            raise ValueError(
                f"{self.display_name}: TAP returned no epoch photometry for source_id {source_id}."
            )
        store_epoch_photometry(source_id, epoch_payload)
        logger.info(
            "%s cached epoch photometry for source_id=%s",
            self.display_name,
            source_id,
        )

    @staticmethod
    def _resolve_source_id(
        *,
        archive_id: str | None,
        object_name: str | None,
    ) -> int | None:
        """Casts archive or caller text to a Gaia ``source_id`` when possible.

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
