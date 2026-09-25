"""Abstract base contract for multi-mission lightcurve providers."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

from astropy.coordinates import SkyCoord
from astropy.table import Table

from lc_discovery.catalog_schema import (
    DISCOVERY_META_MAY_BE_TRUNCATED,
    DISCOVERY_META_TRUNCATION_DETAIL,
    sort_catalog_by_distance,
)
from lc_discovery.discovery_fetch_context import DiscoveryFetchContext
from lc_discovery.lc_key import cache_key, validate_lc_key

logger = logging.getLogger(__name__)

DEFAULT_MAX_DISCOVERY_CATALOG_ROWS = 100
DEFAULT_MAX_DISCOVERY_SEARCH_RADIUS_DEG = 1.0


@dataclass(frozen=True)
class MissionCapabilities:
    """Feature flags describing what a mission provider supports."""

    supports_cone_search: bool = False
    supports_name_resolve: bool = False
    supports_id_lookup: bool = False
    supports_force_refresh: bool = False
    provides_catalog_epoch_period: bool = False
    supports_discovery_time_filter: bool = True
    discovery_catalog_includes_object_class: bool = False
    discovery_catalog_includes_n_points: bool = False


@dataclass(frozen=True)
class MissionDescriptor:
    """Lightweight mission metadata for UI registries."""

    mission_id: str
    display_name: str
    export_profile: str
    capabilities: MissionCapabilities
    is_mock: bool = False


@dataclass(frozen=True)
class MissionArchiveMatch:
    """Mission-native archive identifier selected from a Simbad cross-match."""

    archive_id: str
    match_kind: str
    matched_label: str


class MissionLightcurveProvider(ABC):
    """Mission adapter: catalog search and VO-standard lightcurve fetch."""

    mission_id: str
    display_name: str
    export_profile: str
    capabilities: MissionCapabilities
    is_mock: bool = False

    @abstractmethod
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
        """Returns a standardised catalog table for the requested search.

        Args:
            ra_deg (float, optional): ICRS right ascension in degrees.
            dec_deg (float, optional): ICRS declination in degrees.
            radius_arcsec (float, optional): Cone radius in arcseconds.
            object_name (str, optional): Catalogue name or identifier.
            archive_id (str, optional): Mission-native archive id for direct lookup.
            time_start_mjd (float, optional): Lower time limit in MJD; ``None`` is
                unbounded below (include all data from the beginning).
            time_end_mjd (float, optional): Upper time limit in MJD; ``None`` is
                unbounded above (include all data to the end).
            **mission_options: Mission-specific options.

        Returns:
            astropy.table.Table: Validated catalog table (possibly empty).
        """

    @abstractmethod
    def fetch_lightcurve(
        self,
        lc_key: str,
        *,
        force_refresh: bool = False,
        discovery_context: DiscoveryFetchContext | None = None,
    ) -> bytes:
        """Fetches one lightcurve and returns the calibrated VOTable.

        Args:
            lc_key (str): Opaque fetch handle from a catalog row.
            force_refresh (bool): When True, bypass provider-local caches.
            discovery_context (DiscoveryFetchContext, optional): Discovery session
                metadata. Not part of the public package surface.

        Returns:
            bytes: Calibrated VOTable.
        """

    def resolve_name(self, name: str) -> SkyCoord | None:
        """Resolves an object name to ICRS coordinates when supported.

        Args:
            name (str): User-supplied target name.

        Returns:
            SkyCoord or None: Resolved coordinates, or ``None`` if unsupported.
        """
        return None

    def resolve_target_name(self, name: str) -> MissionArchiveMatch | None:
        """Resolves a user target string to a mission archive id before Simbad.

        Providers may normalise spelling, parse mission-native identifiers, or
        query a local cross-identification table. The Discovery orchestration
        layer calls this after a direct ``object_name`` catalogue search returns
        no rows and before falling back to Simbad.

        Args:
            name (str): Raw Target field text from the UI.

        Returns:
            MissionArchiveMatch or None: Mission-native archive match when
            recognised by provider-specific rules.
        """
        return None

    def pick_archive_id_from_simbad(self, simbad_result) -> MissionArchiveMatch | None:
        """Picks this mission's archive identifier from a Simbad resolve result.

        Args:
            simbad_result: ``SimbadResolveResult`` from ``utils.simbad_resolver``.

        Returns:
            MissionArchiveMatch or None: Mission-native id when recognised.
        """
        return None

    def validate_lc_key(self, lc_key: str) -> bool:
        """Checks whether ``lc_key`` belongs to this mission.

        Args:
            lc_key (str): Serialised fetch handle.

        Returns:
            bool: True when the key is valid for this provider.
        """
        return validate_lc_key(lc_key, mission_id=self.mission_id)

    def cache_key(self, lc_key: str) -> str:
        """Returns a normalised fetch cache hash for ``lc_key``.

        Args:
            lc_key (str): Serialised fetch handle.

        Returns:
            str: SHA-256 hex digest.
        """
        if not self.validate_lc_key(lc_key):
            raise ValueError(f"{self.display_name}: invalid lightcurve key.")
        return cache_key(lc_key)

    def default_search_radius_arcsec(self) -> float:
        """Returns the mission default cone radius in arcseconds.

        Returns:
            float: Suggested search radius for the UI.
        """
        return 10.0

    def max_discovery_catalog_rows(self) -> int:
        """Returns the default row cap used in cone discovery ADQL ``TOP`` clauses.

        Missions may apply this limit to different entities (SSA rows, Gaia
        ``source_id`` rows, or catalogue rows). Use
        ``discovery_cone_limit_entity_label()`` for UI wording.

        Returns:
            int: Row cap for cone searches (default 100).
        """
        return DEFAULT_MAX_DISCOVERY_CATALOG_ROWS

    def discovery_cone_query_row_limit(self) -> int:
        """Returns the numeric cap compared against cone query result counts.

        Returns:
            int: Limit used when deciding whether results may be truncated.
        """
        return self.max_discovery_catalog_rows()

    def discovery_cone_limit_entity_label(self) -> str:
        """Describes what the cone ``TOP`` limit applies to in user-facing text.

        Returns:
            str: Short plural label (e.g. ``catalogue rows``, ``Gaia sources``).
        """
        return "catalogue rows"

    def annotate_discovery_truncation(
        self,
        catalog: Table,
        *,
        cone_query_row_count: int | None,
    ) -> Table:
        """Marks catalogue metadata when a cone query may have hit the row cap.

        Providers should pass the raw row count from the limited query (TAP
        ``TOP``, local truncation, etc.), not the expanded catalogue row count.

        Args:
            catalog (astropy.table.Table): Standardised discovery catalogue.
            cone_query_row_count (int, optional): Rows returned by the limited
                cone query step. When ``None``, no truncation hint is applied.

        Returns:
            astropy.table.Table: Same table with optional ``meta`` hints set.
        """
        if cone_query_row_count is None:
            return catalog
        limit = self.discovery_cone_query_row_limit()
        if int(cone_query_row_count) < limit:
            return catalog
        entity = self.discovery_cone_limit_entity_label()
        catalog.meta[DISCOVERY_META_MAY_BE_TRUNCATED] = True
        catalog.meta[DISCOVERY_META_TRUNCATION_DETAIL] = (
            f"Results may be truncated: the cone search returned {cone_query_row_count} "
            f"{entity}. More matches may exist - try a smaller "
            "radius or a more specific target."
        )
        logger.info(
            "%s cone discovery may be truncated query_rows=%s limit=%s entity=%s",
            self.display_name,
            cone_query_row_count,
            limit,
            entity,
        )
        return catalog

    def finalize_discovery_catalog(
        self,
        catalog: Table,
        *,
        cone_query_row_count: int | None = None,
    ) -> Table:
        """Sorts discovery rows by distance and applies truncation hints.

        Args:
            catalog (astropy.table.Table): Standardised discovery catalogue.
            cone_query_row_count (int, optional): Raw cone query row count before
                catalogue expansion.

        Returns:
            astropy.table.Table: Sorted catalogue with optional truncation meta.
        """
        sorted_catalog = sort_catalog_by_distance(catalog)
        return self.annotate_discovery_truncation(
            sorted_catalog,
            cone_query_row_count=cone_query_row_count,
        )

    def max_discovery_search_radius_deg(self) -> float:
        """Returns the maximum allowed cone search radius in degrees.

        Discovery rejects coordinate cone searches above this limit for the
        mission. Direct archive-id or name lookups are not radius-limited.

        Returns:
            float: Upper bound on cone radius in degrees (default 1).
        """
        return DEFAULT_MAX_DISCOVERY_SEARCH_RADIUS_DEG

    def descriptor(self) -> MissionDescriptor:
        """Builds registry metadata for UI mission selectors.

        Returns:
            MissionDescriptor: Mission identity and capability summary.
        """
        return MissionDescriptor(
            mission_id=self.mission_id,
            display_name=self.display_name,
            export_profile=self.export_profile,
            capabilities=self.capabilities,
            is_mock=self.is_mock,
        )

    def _require_cone_search(
        self,
        *,
        ra_deg: float | None,
        dec_deg: float | None,
        radius_arcsec: float | None,
    ) -> tuple[float, float, float]:
        """Validates cone-search arguments shared by cone-capable missions.

        Args:
            ra_deg (float, optional): ICRS right ascension in degrees.
            dec_deg (float, optional): ICRS declination in degrees.
            radius_arcsec (float, optional): Cone radius in arcseconds.

        Returns:
            tuple[float, float, float]: Validated ``(ra_deg, dec_deg, radius_arcsec)``.

        Raises:
            ValueError: When required values are missing or invalid.
        """
        if ra_deg is None or dec_deg is None or radius_arcsec is None:
            raise ValueError(
                f"{self.display_name}: cone search requires RA, Dec, and radius."
            )
        try:
            ra = float(ra_deg)
            dec = float(dec_deg)
            radius = float(radius_arcsec)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{self.display_name}: RA, Dec, and radius must be numeric."
            ) from exc
        if radius <= 0:
            raise ValueError(f"{self.display_name}: search radius must be positive.")
        max_arcsec = self.max_discovery_search_radius_deg() * 3600.0
        if radius > max_arcsec:
            max_deg = self.max_discovery_search_radius_deg()
            raise ValueError(
                f"{self.display_name}: search radius {radius / 3600.0:g} deg exceeds "
                f"the mission maximum of {max_deg:g} deg."
            )
        return ra, dec, radius

    def _truncate_catalog_table(self, table: Table) -> Table:
        """Truncates a catalogue table to ``max_discovery_catalog_rows``.

        Args:
            table (astropy.table.Table): Candidate discovery catalogue.

        Returns:
            astropy.table.Table: Possibly truncated catalogue copy.
        """
        limit = self.max_discovery_catalog_rows()
        if len(table) <= limit:
            return table
        logger.info(
            "%s truncated discovery catalogue from %s to %s rows.",
            self.display_name,
            len(table),
            limit,
        )
        return table[:limit]
