"""TESS archive lightcurve provider (MAST / Lightkurve products)."""

from __future__ import annotations

import logging

import numpy as np
from astropy.table import Table

from lc_discovery.base import (
    MissionArchiveMatch,
    MissionCapabilities,
    MissionLightcurveProvider,
)
from lc_discovery.catalog_schema import empty_catalog_table
from lc_discovery.lc_key import decode_lc_key
from lc_discovery.providers.tess import config
from lc_discovery.providers.tess.catalog import map_search_table_to_catalog
from lc_discovery.providers.tess.fetch_metadata import votable_from_lightcurve
from lc_discovery.providers.tess.mast_search import search_by_tic, search_cone
from lc_discovery.providers.tess.tess_fetch import (
    download_archive_product,
    purge_archive_product,
    redownload_archive_product,
)
from lc_discovery.providers.tess.tic import (
    mission_archive_match_for_tic,
    parse_tic,
    pick_tic_from_simbad,
)
from lc_discovery.simbad import SimbadResolveResult

logger = logging.getLogger(__name__)


class TessProvider(MissionLightcurveProvider):
    """TESS pipeline light curves via Lightkurve MAST search and download."""

    mission_id = config.PROVIDER_ID
    display_name = config.DISPLAY_NAME
    export_profile = config.EXPORT_PROFILE
    description = (
      "TESS (Transiting Exoplanet Survey Satellite): a NASA space mission observing "
      "the sky in sectors with four wide-field cameras. The light curves are the "
      "archive pipeline products (SPOC, QLP, TESS-SPOC, TARS and other authors), "
      "read through Lightkurve from MAST. Pixel products (cutouts, target pixel "
      "files) are not included.\n"
      "Where from: MAST. Each product is retrieved on first use and kept as a FITS "
      "file in the shared Lightkurve cache.\n"
      "Bands: one broad red band, TESS (about 600 to 1000 nm).\n"
      "Time coverage: from July 2018 (first science sectors) to the present; "
      "ongoing. Each sector lasts about 27 days, and a star is observed only in "
      "the sectors that cover it.\n"
      "Sky: nearly the whole sky, observed sector by sector. The north and south "
      "ecliptic hemispheres were covered in turn, and stars near the ecliptic poles "
      "are observed in many sectors, while those near the ecliptic plane get "
      "only one or two. Cadence ranges from 20 seconds to 30 minutes, "
      "depending on the product and the mission phase.\n"
      "Id lookup: TIC number (for example \"TIC 455790537\"); from Simbad take the "
      "identifier that starts with \"TIC \".\n"
      "Reference: Ricker et al. (2015), JATIS 1, 014003."
    )
    capabilities = MissionCapabilities(
        supports_cone_search=True,
        supports_name_resolve=True,
        supports_id_lookup=True,
        supports_force_refresh=True,
        supports_cache_purge=True,
        provides_catalog_epoch_period=False,
        supports_discovery_time_filter=True,
        discovery_catalog_includes_n_points=False,
        catalog_extra_columns=config.CATALOG_EXTRA_COLUMNS,
    )
    is_mock = False

    def default_search_radius_arcsec(self) -> float:
        """Returns the default cone radius for sky searches.

        Returns:
            float: Default search radius in arcseconds.
        """
        return 21.0

    def max_discovery_catalog_rows(self) -> int:
        """Returns the cone-search catalogue row cap for TESS.

        Returns:
            int: Maximum catalogue rows after mapping a cone search.
        """
        return config.MAX_DISCOVERY_CATALOG_ROWS

    def max_discovery_search_radius_deg(self) -> float:
        """Returns the maximum cone search radius.

        Returns:
            float: Upper bound in degrees (10 arcmin).
        """
        return config.MAX_DISCOVERY_SEARCH_RADIUS_DEG

    def discovery_cone_limit_entity_label(self) -> str:
        """Returns wording for cone truncation notices.

        Returns:
            str: Entity label for the discovery row cap.
        """
        return "TESS archive products"

    def pick_archive_id_from_simbad(
        self,
        simbad_result: SimbadResolveResult,
    ) -> MissionArchiveMatch | None:
        """Selects a TIC from Simbad cross-identifiers.

        Args:
            simbad_result (SimbadResolveResult): Shared Simbad resolve payload.

        Returns:
            MissionArchiveMatch or None: TIC match when recognised.
        """
        return pick_tic_from_simbad(simbad_result)

    def resolve_target_name(self, name: str) -> MissionArchiveMatch | None:
        """Parses TIC strings before Simbad name resolution.

        Args:
            name (str): Raw Target field text from the caller.

        Returns:
            MissionArchiveMatch or None: TIC match when recognised.
        """
        tic = parse_tic(name)
        if tic is None:
            return None
        return mission_archive_match_for_tic(tic)

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
        """Queries MAST for TESS archive products.

        Direct lookup uses TIC (from ``archive_id`` or a TIC ``object_name``).
        Cone search keeps every product in the cone, not only the closest TIC.

        Args:
            ra_deg (float, optional): ICRS right ascension in degrees.
            dec_deg (float, optional): ICRS declination in degrees.
            radius_arcsec (float, optional): Cone radius in arcseconds.
            object_name (str, optional): TIC string from the Target field.
            archive_id (str, optional): TIC for direct lookup.
            time_start_mjd (float, optional): Lower time limit in MJD.
            time_end_mjd (float, optional): Upper time limit in MJD.
            **mission_options: Reserved for future provider options.

        Returns:
            astropy.table.Table: Standardised catalogue table (possibly empty).
        """
        tic = self._resolve_tic(archive_id=archive_id, object_name=object_name)
        if tic is not None:
            search_table = search_by_tic(tic)
            catalog = map_search_table_to_catalog(
                search_table,
                provider_id=self.mission_id,
            )
            return self._apply_time_window(
                catalog,
                time_start_mjd=time_start_mjd,
                time_end_mjd=time_end_mjd,
            )

        if ra_deg is not None and dec_deg is not None and radius_arcsec is not None:
            ra, dec, radius = self._require_cone_search(
                ra_deg=ra_deg,
                dec_deg=dec_deg,
                radius_arcsec=radius_arcsec,
            )
            search_table = search_cone(ra, dec, radius)
            catalog = map_search_table_to_catalog(
                search_table,
                provider_id=self.mission_id,
                centre_ra_deg=ra,
                centre_dec_deg=dec,
            )
            catalog = self._apply_time_window(
                catalog,
                time_start_mjd=time_start_mjd,
                time_end_mjd=time_end_mjd,
            )
            limited = catalog[: self.max_discovery_catalog_rows()]
            return self.finalize_discovery_catalog(
                limited,
                cone_query_row_count=len(catalog),
            )

        return empty_catalog_table(extra_columns=config.CATALOG_EXTRA_COLUMNS)

    def fetch_lightcurve(
        self,
        lc_key: str,
        *,
        force_refresh: bool = False,
        discovery_context=None,
    ) -> bytes:
        """Downloads one MAST product and issues a multi-column VOTable.

        Args:
            lc_key (str): Opaque fetch handle from a catalogue row.
            force_refresh (bool): When True, delete the cached FITS and download
                it from MAST again.
            discovery_context: Unused; reserved for host lookup labels.

        Returns:
            bytes: Calibrated VOTable.

        Raises:
            ValueError: When the key is invalid or the download is not unique.
        """
        if not self.validate_lc_key(lc_key):
            raise ValueError(f"{self.display_name}: invalid lightcurve key.")
        payload = decode_lc_key(lc_key)["payload"]
        tic = int(payload["tic"])
        sector = int(payload["sector"])
        author = str(payload["author"])
        exptime = float(payload["exptime"])
        if force_refresh:
            _purged, lc, pointer = redownload_archive_product(
                tic=tic, sector=sector, author=author, exptime=exptime
            )
        else:
            lc, pointer = download_archive_product(
                tic=tic, sector=sector, author=author, exptime=exptime
            )
        return votable_from_lightcurve(
            lc,
            tic=tic,
            sector=sector,
            author=author,
            exptime=exptime,
            mast_pointer=pointer,
        )

    def purge_cached_product(self, lc_key: str) -> bool:
        """Deletes the cached FITS file of one TESS product.

        Args:
            lc_key (str): Opaque fetch handle from a catalogue row.

        Returns:
            bool: True when a file was deleted, False when none was cached.

        Raises:
            ValueError: When the key is invalid or MAST finds no unique product.
        """
        if not self.validate_lc_key(lc_key):
            raise ValueError(f"{self.display_name}: invalid lightcurve key.")
        payload = decode_lc_key(lc_key)["payload"]
        return purge_archive_product(
            tic=int(payload["tic"]),
            sector=int(payload["sector"]),
            author=str(payload["author"]),
            exptime=float(payload["exptime"]),
        )

    def _resolve_tic(
        self,
        *,
        archive_id: str | None,
        object_name: str | None,
    ) -> int | None:
        """Resolves a TIC from archive id or object name.

        Args:
            archive_id (str, optional): Direct TIC string.
            object_name (str, optional): Target field text.

        Returns:
            int or None: TIC when recognised.
        """
        for candidate in (archive_id, object_name):
            tic = parse_tic(candidate)
            if tic is not None:
                return tic
        return None

    def _apply_time_window(
        self,
        catalog: Table,
        *,
        time_start_mjd: float | None,
        time_end_mjd: float | None,
    ) -> Table:
        """Keeps catalogue rows whose MAST coverage overlaps the MJD window.

        Args:
            catalog (astropy.table.Table): Mapped catalogue.
            time_start_mjd (float, optional): Lower bound.
            time_end_mjd (float, optional): Upper bound.

        Returns:
            astropy.table.Table: Filtered catalogue.
        """
        if time_start_mjd is None and time_end_mjd is None:
            return catalog
        if len(catalog) == 0:
            return catalog
        keep = []
        for row in catalog:
            t_min = row["t_min"]
            t_max = row["t_max"]
            if t_min is np.ma.masked or t_max is np.ma.masked:
                keep.append(False)
                continue
            start = float(t_min)
            end = float(t_max)
            if time_start_mjd is not None and end < float(time_start_mjd):
                keep.append(False)
                continue
            if time_end_mjd is not None and start > float(time_end_mjd):
                keep.append(False)
                continue
            keep.append(True)
        return catalog[np.array(keep, dtype=bool)]
