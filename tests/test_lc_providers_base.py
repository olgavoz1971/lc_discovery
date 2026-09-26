"""Tests for shared lightcurve provider base behaviour."""

from __future__ import annotations

import pytest

from lc_discovery.base import (
    DEFAULT_MAX_DISCOVERY_CATALOG_ROWS,
    DEFAULT_MAX_DISCOVERY_SEARCH_RADIUS_DEG,
)
from lc_discovery.providers.gaia_dr3_aip.provider import GaiaDr3AipProvider
from lc_discovery.providers.gaia_dr3_ari.provider import GaiaDr3AriProvider
from lc_discovery.providers.ogle_ocvs.provider import OgleOcvsProvider
from lc_discovery.catalog_schema import (
    empty_catalog_table,
    read_discovery_truncation_meta,
)
from lc_discovery.registry import PROVIDERS
from lc_discovery.tap.adql import adql_top_limit_clause


def test_default_max_discovery_catalog_rows():
    """Providers inherit a default cone-search row cap of 100."""
    provider = GaiaDr3AipProvider()
    assert provider.max_discovery_catalog_rows() == DEFAULT_MAX_DISCOVERY_CATALOG_ROWS
    assert DEFAULT_MAX_DISCOVERY_CATALOG_ROWS == 100


def test_default_max_discovery_search_radius_deg():
    """Providers inherit a default cone radius cap of one degree."""
    provider = GaiaDr3AipProvider()
    assert provider.max_discovery_search_radius_deg() == DEFAULT_MAX_DISCOVERY_SEARCH_RADIUS_DEG
    assert DEFAULT_MAX_DISCOVERY_SEARCH_RADIUS_DEG == 1.0


def test_registered_provider_search_radius_caps():
    """Each mission exposes the agreed discovery cone radius upper bound."""
    expected = {
        "gaia_dr3_aip": 1.0,
        "gaia_dr3_ari": 1.0,
        "asassn": 10.0,
        "gaia_dr3_veb": 10.0,
        "upjs_ts": 30.0,
        "personal_ts": 30.0,
        "ogle_ocvs": 10.0,
        "ztf_dr24": 1.0,
    }
    for mission_id, max_deg in expected.items():
        assert PROVIDERS[mission_id].max_discovery_search_radius_deg() == max_deg


def test_require_cone_search_rejects_radius_above_mission_max():
    """Cone validation rejects radii above the provider maximum."""
    provider = GaiaDr3AipProvider()
    with pytest.raises(ValueError, match="exceeds the mission maximum"):
        provider._require_cone_search(
            ra_deg=346.0,
            dec_deg=47.0,
            radius_arcsec=7200.0,
        )


def test_require_cone_search_accepts_radius_at_mission_max():
    """Cone validation accepts radii equal to the provider maximum."""
    provider = OgleOcvsProvider()
    ra, dec, radius = provider._require_cone_search(
        ra_deg=17.0,
        dec_deg=-72.0,
        radius_arcsec=10.0 * 3600.0,
    )
    assert radius == pytest.approx(36000.0)
    assert ra == pytest.approx(17.0)


def test_adql_top_limit_clause():
    """ADQL TOP prefix is omitted unless a positive limit is supplied."""
    assert adql_top_limit_clause(None) == ""
    assert adql_top_limit_clause(100) == "TOP 100 "


def test_annotate_discovery_truncation_at_limit():
    """Hitting the cone query cap sets catalogue meta for the UI layer."""
    provider = OgleOcvsProvider()
    catalog = empty_catalog_table()
    annotated = provider.annotate_discovery_truncation(catalog, cone_query_row_count=100)
    may_be, detail = read_discovery_truncation_meta(annotated)
    assert may_be is True
    assert detail is not None
    assert "100" in detail
    assert "catalogue rows" in detail


def test_annotate_discovery_truncation_below_limit():
    """Fewer query rows than the cap does not set truncation meta."""
    provider = OgleOcvsProvider()
    catalog = empty_catalog_table()
    annotated = provider.annotate_discovery_truncation(catalog, cone_query_row_count=99)
    may_be, _detail = read_discovery_truncation_meta(annotated)
    assert may_be is False


def test_gaia_ari_truncation_entity_label():
    """Gaia missions compare TOP against source rows, not expanded band rows."""
    provider = GaiaDr3AriProvider()
    assert provider.discovery_cone_limit_entity_label() == "Gaia sources"
    catalog = empty_catalog_table()
    annotated = provider.annotate_discovery_truncation(catalog, cone_query_row_count=100)
    _may_be, detail = read_discovery_truncation_meta(annotated)
    assert detail is not None
    assert "Gaia sources" in detail


def test_gaia_aip_truncation_entity_label():
    """Gaia@AIP uses the same source-row semantics as ARI for truncation hints."""
    provider = GaiaDr3AipProvider()
    assert provider.discovery_cone_limit_entity_label() == "Gaia sources"
