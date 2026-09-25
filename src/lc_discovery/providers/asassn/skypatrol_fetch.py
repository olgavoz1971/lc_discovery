"""ASAS-SN Sky Patrol discovery and lightcurve download (no pickle cache)."""

from __future__ import annotations

import logging
from typing import Any, Callable, TypeVar

import numpy as np
import pandas as pd
import requests
from numpy import isnan

from lc_discovery.providers.asassn import config
from lc_discovery.providers.asassn.skypatrol_client import create_skypatrol_client
from lc_discovery.providers.asassn.skypatrol_cone_url import skypatrol_cone_centre_for_lookup_url
from skvo_veb.utils.lc_config import resolve_catalog_epoch
from skvo_veb.utils.my_tools import PipeException

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


def _raise_skypatrol_pipe_error(context: str, exc: Exception) -> None:
    """Maps Sky Patrol client failures to a user-facing ``PipeException``.

    Args:
        context (str): Short operation label (for example ``cone search``).
        exc (Exception): Failure raised by ``pyasassn`` or ``requests``.

    Raises:
        PipeException: Always; never returns.
    """
    if isinstance(exc, requests.HTTPError):
        response = exc.response
        status = response.status_code if response is not None else "unknown"
        logger.error(
            "%s Sky Patrol %s HTTP %s: %s",
            config.DISPLAY_NAME,
            context,
            status,
            exc,
        )
        raise PipeException(
            f"{config.DISPLAY_NAME}: Sky Patrol {context} failed (HTTP {status}). "
            "The service may be overloaded or reject this query - try again later "
            "or use a smaller search radius."
        ) from exc
    logger.error("%s Sky Patrol %s failed: %s", config.DISPLAY_NAME, context, exc)
    raise PipeException(
        f"{config.DISPLAY_NAME}: Sky Patrol {context} failed: {exc}"
    ) from exc


def _skypatrol_call(context: str, operation: Callable[[], _T]) -> _T:
    """Runs a Sky Patrol client call and converts failures to ``PipeException``.

    Args:
        context (str): Short operation label for error messages.
        operation (callable): Zero-argument callable invoking the client.

    Returns:
        object: Return value from ``operation``.

    Raises:
        PipeException: When the client or HTTP layer fails.
    """
    try:
        return operation()
    except PipeException:
        raise
    except Exception as exc:
        _raise_skypatrol_pipe_error(context, exc)


def _ensure_dataframe(result: Any, *, context: str) -> pd.DataFrame:
    """Normalises a Sky Patrol metadata response to a DataFrame.

    Args:
        result (object): Client return value.
        context (str): Short label for error messages.

    Returns:
        pandas.DataFrame: Catalogue metadata (possibly empty).

    Raises:
        PipeException: When the response type is unexpected.
    """
    if isinstance(result, pd.DataFrame):
        return result
    raise PipeException(f"{config.DISPLAY_NAME}: {context} did not return a pandas DataFrame.")


def _discovery_column_list() -> list[str]:
    """Returns the shared ``stellar_main`` discovery column list.

    Returns:
        list[str]: Column names for ``cone_search`` / ``query_list``.
    """
    return list(config.STELLAR_MAIN_DISCOVERY_COLS)


def fetch_discovery_cone(
    *,
    ra_deg: float,
    dec_deg: float,
    radius_arcsec: float,
    client: Any | None = None,
) -> pd.DataFrame:
    """Runs metadata cone search on ``stellar_main``.

    Args:
        ra_deg (float): Cone centre RA in degrees.
        dec_deg (float): Cone centre Dec in degrees.
        radius_arcsec (float): Cone radius in arcseconds.
        client (object, optional): Injected ``SkyPatrolClient`` for tests.

    Returns:
        pandas.DataFrame: Source metadata including ``pstarrs_g_mag``.
    """
    sp = client or create_skypatrol_client()
    ra_api, dec_api = skypatrol_cone_centre_for_lookup_url(ra_deg, dec_deg)
    result = _skypatrol_call(
        "cone search",
        lambda: sp.cone_search(
            ra_api,
            dec_api,
            float(radius_arcsec),
            units="arcsec",
            catalog=config.STELLAR_MAIN_CATALOG,
            cols=_discovery_column_list(),
            download=False,
        ),
    )
    return _ensure_dataframe(result, context="cone_search")


def fetch_discovery_by_gaia_id(
    gaia_id: int | str,
    *,
    client: Any | None = None,
) -> pd.DataFrame:
    """Looks up one Gaia DR3 id on ``stellar_main`` without downloading photometry.

    Args:
        gaia_id (int or str): Gaia DR3 ``source_id``.
        client (object, optional): Injected client for tests.

    Returns:
        pandas.DataFrame: Zero or one metadata rows.
    """
    sp = client or create_skypatrol_client()
    gid = int(gaia_id)
    result = _skypatrol_call(
        "Gaia id lookup",
        lambda: sp.query_list(
            [gid],
            id_col="gaia_id",
            catalog=config.STELLAR_MAIN_CATALOG,
            cols=_discovery_column_list(),
            download=False,
        ),
    )
    return _ensure_dataframe(result, context="query_list(gaia_id)")


def fetch_discovery_by_asas_sn_id(
    asas_sn_id: int | str,
    *,
    client: Any | None = None,
) -> pd.DataFrame:
    """Looks up one ASAS-SN id on ``stellar_main`` (metadata only).

    Args:
        asas_sn_id (int or str): Sky Patrol source identifier.
        client (object, optional): Injected client for tests.

    Returns:
        pandas.DataFrame: Zero or one metadata rows.
    """
    sp = client or create_skypatrol_client()
    sid = int(asas_sn_id)
    result = _skypatrol_call(
        "ASAS-SN id lookup",
        lambda: sp.query_list(
            [sid],
            id_col="asas_sn_id",
            catalog=config.STELLAR_MAIN_CATALOG,
            cols=_discovery_column_list(),
            download=False,
        ),
    )
    return _ensure_dataframe(result, context="query_list(asas_sn_id)")


def fetch_discovery_by_simbad_name(
    name: str,
    *,
    client: Any | None = None,
) -> pd.DataFrame:
    """Resolves a Simbad name and loads ``stellar_main`` metadata for the match.

    Args:
        name (str): Simbad-resolvable target name.
        client (object, optional): Injected client for tests.

    Returns:
        pandas.DataFrame: Zero or one discovery rows with ``pstarrs_g_mag``.

    Raises:
        PipeException: When Simbad lookup fails or returns no ``asas_sn_id``.
    """
    sp = client or create_skypatrol_client()
    lookup = _skypatrol_call(
        "Simbad lookup",
        lambda: sp.simbad_lookup(str(name).strip(), download=False),
    )
    lookup_df = _ensure_dataframe(lookup, context="simbad_lookup")
    if len(lookup_df) == 0:
        return lookup_df
    if "asas_sn_id" not in lookup_df.columns:
        raise PipeException(
            f"{config.DISPLAY_NAME}: simbad_lookup result missing asas_sn_id."
        )
    asas_sn_id = lookup_df["asas_sn_id"].iloc[0]
    meta = fetch_discovery_by_asas_sn_id(asas_sn_id, client=sp)
    if len(meta) == 0:
        return meta
    return meta


def _photometry_dataframe(collection: Any) -> pd.DataFrame:
    """Extracts the photometry table from a download response.

    Args:
        collection (object): ``LightCurveCollection`` or DataFrame.

    Returns:
        pandas.DataFrame: Photometry table.

    Raises:
        PipeException: When no photometry table is present.
    """
    if isinstance(collection, pd.DataFrame):
        return collection
    data = getattr(collection, "data", None)
    if isinstance(data, pd.DataFrame):
        return data
    raise PipeException(
        f"{config.DISPLAY_NAME}: lightcurve download did not contain photometry data."
    )


def fetch_epoch_period_for_asas_sn_id(
    asas_sn_id: int | str,
    *,
    client: Any | None = None,
) -> tuple[float | None, float | None]:
    """Queries ``aavsovsx`` for folding epoch and period at fetch time.

    Args:
        asas_sn_id (int or str): Sky Patrol source identifier.
        client (object, optional): Injected client for tests.

    Returns:
        tuple[float | None, float | None]: ``(epoch_jd, period_days)``.
    """
    sp = client or create_skypatrol_client()
    sid = int(asas_sn_id)
    sql = f"SELECT epoch, period FROM aavsovsx WHERE asas_sn_id = {sid} LIMIT 1"
    try:
        result = sp.adql_query(sql, download=False)
        frame = _ensure_dataframe(result, context="aavsovsx epoch/period")
    except Exception as exc:
        logger.warning(
            "%s aavsovsx lookup failed for asas_sn_id=%s: %s",
            config.DISPLAY_NAME,
            sid,
            exc,
        )
        return None, None
    if len(frame) == 0:
        return None, None
    epoch = resolve_catalog_epoch(frame.get("epoch", [None])[0])
    period = frame.get("period", [None])[0]
    if period is None or (isinstance(period, float) and isnan(period)):
        period = None
    else:
        try:
            period = float(period)
        except (TypeError, ValueError):
            period = None
    return epoch, period


def fetch_photometry_by_asas_sn_id(
    asas_sn_id: int | str,
    *,
    client: Any | None = None,
) -> pd.DataFrame:
    """Downloads full epoch photometry for one ASAS-SN source.

    Args:
        asas_sn_id (int or str): Sky Patrol source identifier.
        client (object, optional): Injected client for tests.

    Returns:
        pandas.DataFrame: All bands in one table (filter with ``phot_filter``).

    Raises:
        PipeException: When the download is empty or fails.
    """
    sp = client or create_skypatrol_client()
    sid = int(asas_sn_id)
    result = _skypatrol_call(
        "photometry download",
        lambda: sp.query_list(
            [sid],
            id_col="asas_sn_id",
            catalog=config.STELLAR_MAIN_CATALOG,
            download=True,
        ),
    )
    frame = _photometry_dataframe(result)
    if frame.empty:
        raise PipeException(
            f"{config.DISPLAY_NAME}: no photometry returned for asas_sn_id={sid}."
        )
    return frame


def slice_band_photometry(
    photometry: pd.DataFrame,
    *,
    band: str,
    asas_sn_id: int | str,
) -> pd.DataFrame:
    """Selects one ``phot_filter`` band from a Sky Patrol photometry table.

    Args:
        photometry (pandas.DataFrame): Full download table.
        band (str): ASAS-SN filter code (``g`` or ``V``).
        asas_sn_id (int or str): Source id for error messages.

    Returns:
        pandas.DataFrame: Columns ``jd``, ``flux``, ``flux_err``, and optionally
        ``camera`` when present in the download. Rows with missing ``jd`` or
        ``flux`` are removed. A missing ``flux_err`` is kept.

    Raises:
        PipeException: When the band has no rows or columns are missing.
    """
    band_code = config.band_spec_for_code(band).band_code
    if "phot_filter" not in photometry.columns:
        raise PipeException(
            f"{config.DISPLAY_NAME}: downloaded table missing phot_filter column."
        )
    subset = photometry[photometry["phot_filter"] == band_code]
    required = ("jd", "flux", "flux_err")
    missing = [name for name in required if name not in subset.columns]
    if missing:
        raise PipeException(
            f"{config.DISPLAY_NAME}: photometry missing columns {missing}."
        )
    keep_cols = list(required)
    if "camera" in subset.columns:
        keep_cols.append("camera")
    band_df = subset[keep_cols].dropna(subset=["jd", "flux"])
    if band_df.empty:
        raise PipeException(
            f"{config.DISPLAY_NAME}: asas_sn_id {asas_sn_id} has no observations "
            f"with filter {band_code!r}."
        )
    return band_df.reset_index(drop=True)
