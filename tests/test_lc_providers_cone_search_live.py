"""Live cone-search integration tests for Lightcurve Discovery providers.

Run with::

    pytest -m integration tests/test_lc_providers_cone_search_live.py

The coordinates target Gaia DR3 source 1936512041221649536 (AA And vicinity).
"""

from __future__ import annotations

import pytest

from lc_discovery.registry import PROVIDERS, get_provider

CONE_RA_DEG = 346.34517
CONE_DEC_DEG = 47.67631
CONE_RADIUS_ARCSEC = 10.0

# Providers expected to return three band rows for the AA And test field.
_PROVIDERS_WITH_KNOWN_HITS = frozenset(
    {
        "gaia_dr3_aip",
        "gaia_dr3_ari",
        "gaia_dr3_veb",
    }
)


def _cone_capable_mission_ids() -> list[str]:
    """Returns registered mission slugs that advertise cone search support.

    Returns:
        list[str]: Sorted mission identifiers.
    """
    return sorted(
        mission_id
        for mission_id, provider in PROVIDERS.items()
        if provider.capabilities.supports_cone_search
    )


@pytest.mark.integration
@pytest.mark.parametrize("mission_id", _cone_capable_mission_ids())
def test_cone_search_by_coordinates(mission_id: str):
    """Each cone-capable provider accepts an ICRS cone at the AA And test field."""
    provider = get_provider(mission_id)
    catalog = provider.search_catalog(
        ra_deg=CONE_RA_DEG,
        dec_deg=CONE_DEC_DEG,
        radius_arcsec=CONE_RADIUS_ARCSEC,
    )

    if mission_id in _PROVIDERS_WITH_KNOWN_HITS:
        assert len(catalog) == 3, (
            f"{provider.display_name}: expected three band rows near "
            f"({CONE_RA_DEG}, {CONE_DEC_DEG}), got {len(catalog)}"
        )
        assert set(catalog["filter_name"]) == {"Gaia G", "Gaia BP", "Gaia RP"}
    else:
        assert len(catalog) == 0, (
            f"{provider.display_name}: expected no rows at the test field, got {len(catalog)}"
        )
