"""Abstract base contract for multi-mission lightcurve providers."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

from astropy.coordinates import SkyCoord
from astropy.table import Table

from lc_discovery.catalog_schema import (
    CatalogExtraColumn,
    DISCOVERY_META_MAY_BE_TRUNCATED,
    DISCOVERY_META_TRUNCATION_DETAIL,
    sort_catalog_by_distance,
)
from lc_discovery.coverage import MissionCoverage, validate_coverage
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
    supports_cache_purge: bool = False
    provides_catalog_epoch_period: bool = False
    supports_discovery_time_filter: bool = True
    discovery_catalog_includes_object_class: bool = False
    discovery_catalog_includes_n_points: bool = False
    catalog_extra_columns: tuple[CatalogExtraColumn, ...] = ()


@dataclass(frozen=True)
class MissionDescriptor:
    """Lightweight mission metadata."""

    mission_id: str
    display_name: str
    export_profile: str
    capabilities: MissionCapabilities
    is_mock: bool = False
    description: str = ""
    data_group: str = ""
    is_subset: bool = False
    subset_description: str = ""
    group_rank: int = 1
    coverage: MissionCoverage | None = None


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
    description: str  # human-readable checklist text, see docs/adding_a_lightcurve_provider.md
    data_group: str  # shared content id; own mission_id when nothing else serves the same data
    is_subset: bool  # True when this mission serves only part of the data_group content
    subset_description: str  # what the subset holds (required when is_subset is True, else "")
    group_rank: int  # order among non-subset members of the group; lower is asked first
    coverage: MissionCoverage  # space, time and spectrum of the whole mission (None parts = unknown)
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
            force_refresh (bool): When True, discard the locally cached product
                (where the mission keeps one) and download it again.
            discovery_context (DiscoveryFetchContext, optional): Discovery session
                metadata. Not part of the public package surface.

        Returns:
            bytes: Calibrated VOTable.
        """

    def purge_cached_product(self, lc_key: str) -> bool:
        """Deletes the locally cached product of one light curve.

        Only missions with ``capabilities.supports_cache_purge`` keep a local
        product cache; the next ``fetch`` then downloads the product again.

        Args:
            lc_key (str): Opaque fetch handle from a catalogue row.

        Returns:
            bool: True when a cached file was deleted, False when none existed.

        Raises:
            ValueError: When this mission keeps no local product cache.
        """
        raise ValueError(f"{self.display_name}: keeps no local product cache to purge.")

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
            name (str): Raw Target field text from the caller.

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
            float: Suggested search radius.
        """
        return 10.0

    def max_discovery_catalog_rows(self) -> int:
        """Returns the default row cap used in cone discovery ADQL ``TOP`` clauses.

        Missions may apply this limit to different entities (SSA rows, Gaia
        ``source_id`` rows, or catalogue rows). Use
        ``discovery_cone_limit_entity_label()`` for wording.

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
        """Builds registry metadata for this mission.

        Returns:
            MissionDescriptor: Mission identity and capability summary.

        Raises:
            ValueError: When the provider does not set ``description``, one
                of the group attributes (``data_group``, ``is_subset``,
                ``subset_description``, ``group_rank``) or ``coverage``, or
                sets one with the wrong type or an invalid value.
        """
        values = {
            name: self._required_attribute(name)
            for name in (
                "description",
                "data_group",
                "is_subset",
                "subset_description",
                "group_rank",
                "coverage",
            )
        }
        self._validate_group_attributes(values)
        validate_coverage(self.mission_id, values["coverage"])
        return MissionDescriptor(
            mission_id=self.mission_id,
            display_name=self.display_name,
            export_profile=self.export_profile,
            capabilities=self.capabilities,
            is_mock=self.is_mock,
            **values,
        )

    def _required_attribute(self, name: str):
        """Reads a mandatory provider attribute.

        Args:
            name (str): Attribute name.

        Returns:
            object: The attribute value.

        Raises:
            ValueError: When the provider does not define the attribute.
        """
        try:
            return getattr(self, name)
        except AttributeError:
            raise ValueError(
                f"Mission '{self.mission_id}': the provider must set '{name}' "
                "(see docs/adding_a_lightcurve_provider.md)."
            ) from None

    def _validate_group_attributes(self, values: dict) -> None:
        """Checks the types and values of the data-group attributes.

        Args:
            values (dict): Attribute values read from the provider.

        Raises:
            ValueError: When a value has the wrong type or is not allowed.
        """
        mission = self.mission_id
        group = values["data_group"]
        if not isinstance(group, str) or not group.strip():
            raise ValueError(f"Mission '{mission}': 'data_group' must be a non-empty string.")
        if not isinstance(values["is_subset"], bool):
            raise ValueError(f"Mission '{mission}': 'is_subset' must be a bool.")
        rank = values["group_rank"]
        if isinstance(rank, bool) or not isinstance(rank, int) or rank < 1:
            raise ValueError(f"Mission '{mission}': 'group_rank' must be an integer >= 1.")
        text = values["subset_description"]
        if not isinstance(text, str):
            raise ValueError(f"Mission '{mission}': 'subset_description' must be a string.")
        if values["is_subset"] and not text.strip():
            raise ValueError(
                f"Mission '{mission}': 'subset_description' is required when 'is_subset' is True."
            )
        if not values["is_subset"] and text.strip():
            raise ValueError(
                f"Mission '{mission}': 'subset_description' must be empty when 'is_subset' is False."
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
