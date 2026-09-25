"""Discovery session context passed from the UI into lightcurve fetch."""

from __future__ import annotations

from dataclasses import dataclass

SEARCH_MODE_SIMBAD_CONE = "simbad_cone"

LOOKUP_ASSOCIATION_MAX_ARCSEC = 5.0


def _radius_to_arcsec(radius_value: float, radius_unit: str) -> float:
    """Converts a UI radius to arcseconds without importing the orchestrator module.

    Args:
        radius_value (float): Numeric radius from the tools panel.
        radius_unit (str): ``arcsec``, ``arcmin``, or ``deg``.

    Returns:
        float: Radius in arcseconds.
    """
    unit = str(radius_unit or "arcsec").strip().lower()
    if unit == "arcsec":
        return float(radius_value)
    if unit == "arcmin":
        return float(radius_value) * 60.0
    if unit == "deg":
        return float(radius_value) * 3600.0
    return float(radius_value)


@dataclass(frozen=True)
class DiscoveryFetchContext:
    """Lightweight search metadata for provider fetch enrichment.

    Attributes:
        search_mode (str, optional): Orchestrator search strategy identifier.
        user_target (str, optional): Raw Target field text from the UI.
        simbad_main_id (str, optional): Simbad main identifier when resolved.
        radius_arcsec (float, optional): Cone radius used for the search in arcseconds.
        distance_arcsec (float, optional): Separation of the selected catalogue row
            from the search centre in arcseconds.
        fetch_quality (str): Provider-specific quality mode (e.g. ZTF ``raw``).
    """

    search_mode: str | None = None
    user_target: str | None = None
    simbad_main_id: str | None = None
    radius_arcsec: float | None = None
    distance_arcsec: float | None = None
    fetch_quality: str = "raw"


def discovery_fetch_context_from_store(
    store: dict | None,
    catalog_row: dict | None,
) -> DiscoveryFetchContext | None:
    """Builds a fetch context from Discovery ``dcc.Store`` payload and one AgGrid row.

    Args:
        store (dict, optional): Serialised ``SearchOutcome`` metadata.
        catalog_row (dict, optional): Selected catalogue row dict.

    Returns:
        DiscoveryFetchContext or None: Context when ``store`` is present.
    """
    if not store:
        return None
    radius_arcsec = None
    radius_value = store.get("radius_value")
    radius_unit = store.get("radius_unit")
    if radius_value is not None and radius_unit:
        try:
            radius_arcsec = float(
                _radius_to_arcsec(float(radius_value), str(radius_unit))
            )
        except (TypeError, ValueError):
            radius_arcsec = None
    distance_arcsec = None
    if catalog_row is not None:
        raw_dist = catalog_row.get("distance_arcsec")
        if raw_dist is not None and raw_dist != "":
            try:
                distance_arcsec = float(raw_dist)
            except (TypeError, ValueError):
                distance_arcsec = None
    return DiscoveryFetchContext(
        search_mode=store.get("search_mode"),
        user_target=store.get("user_target"),
        simbad_main_id=store.get("simbad_main_id"),
        radius_arcsec=radius_arcsec,
        distance_arcsec=distance_arcsec,
        fetch_quality=str(store.get("fetch_quality") or "raw"),
    )


def lookup_label_from_context(context: DiscoveryFetchContext | None) -> str | None:
    """Returns the human lookup label for a named Simbad-centred cone search.

    Args:
        context (DiscoveryFetchContext, optional): Discovery fetch context.

    Returns:
        str or None: Simbad main id or user target when applicable.
    """
    if context is None or context.search_mode != SEARCH_MODE_SIMBAD_CONE:
        return None
    for candidate in (context.simbad_main_id, context.user_target):
        if candidate and str(candidate).strip():
            return str(candidate).strip()
    return None


def effective_lookup_association_arcsec(
    radius_arcsec: float | None,
    *,
    max_arcsec: float = LOOKUP_ASSOCIATION_MAX_ARCSEC,
) -> float:
    """Computes τ_eff = min(cone radius, association cap) in arcseconds.

    Args:
        radius_arcsec (float, optional): Discovery cone radius in arcseconds.
        max_arcsec (float): Provider cap on positional lookup association.

    Returns:
        float: Separation threshold for inheriting a Simbad lookup label.
    """
    cap = float(max_arcsec)
    if radius_arcsec is None:
        return cap
    try:
        radius = float(radius_arcsec)
    except (TypeError, ValueError):
        return cap
    if radius <= 0:
        return cap
    return min(radius, cap)


def resolve_lookup_name_for_discovery_fetch(
    context: DiscoveryFetchContext | None,
    *,
    max_association_arcsec: float = LOOKUP_ASSOCIATION_MAX_ARCSEC,
) -> str | None:
    """Returns a lookup label when a Simbad-centred cone row is close enough.

    Args:
        context (DiscoveryFetchContext, optional): Discovery session context.
        max_association_arcsec (float): Positional association cap in arcseconds.

    Returns:
        str or None: Simbad or user lookup label, or ``None`` when not applicable.
    """
    lookup = lookup_label_from_context(context)
    if lookup is None or context is None:
        return None
    if context.distance_arcsec is None:
        return None
    tau = effective_lookup_association_arcsec(
        context.radius_arcsec,
        max_arcsec=max_association_arcsec,
    )
    try:
        distance = float(context.distance_arcsec)
    except (TypeError, ValueError):
        return None
    if distance > tau:
        return None
    return lookup
