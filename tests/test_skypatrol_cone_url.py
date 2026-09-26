"""Tests for Sky Patrol lookup_cone zero-coordinate workaround."""

from __future__ import annotations

import pandas as pd
import pytest

from lc_discovery.providers.asassn.skypatrol_cone_url import (
    skypatrol_cone_centre_for_lookup_url,
)
from lc_discovery.providers.asassn.skypatrol_fetch import fetch_discovery_cone


def test_skypatrol_cone_centre_nudges_exact_zero_ra_and_dec():
    """Exact zero RA/Dec are offset for the Hawaii path parser."""
    ra, dec = skypatrol_cone_centre_for_lookup_url(0.0, 0.0)
    assert ra == pytest.approx(1e-8)
    assert dec == pytest.approx(1e-8)

    ra, dec = skypatrol_cone_centre_for_lookup_url(1.0, 0.0)
    assert ra == pytest.approx(1.0)
    assert dec == pytest.approx(1e-8)

    ra, dec = skypatrol_cone_centre_for_lookup_url(0.0, -30.0)
    assert ra == pytest.approx(1e-8)
    assert dec == pytest.approx(-30.0)


def test_skypatrol_cone_centre_leaves_nonzero_unchanged():
    """Non-zero centres are not modified."""
    ra, dec = skypatrol_cone_centre_for_lookup_url(0.0001, 0.00001)
    assert ra == pytest.approx(0.0001)
    assert dec == pytest.approx(0.00001)


def test_fetch_discovery_cone_passes_nudged_coords_to_client():
    """Cone fetch applies the workaround before pyasassn cone_search."""

    class _RecordingClient:
        def __init__(self):
            self.last_cone_args: tuple[float, float, float] | None = None

        def cone_search(self, ra, dec, radius, **kwargs):
            self.last_cone_args = (float(ra), float(dec), float(radius))
            return pd.DataFrame(
                columns=["asas_sn_id", "ra_deg", "dec_deg", "pstarrs_g_mag"]
            )

    client = _RecordingClient()
    fetch_discovery_cone(
        ra_deg=1.0,
        dec_deg=0.0,
        radius_arcsec=30.0,
        client=client,
    )
    assert client.last_cone_args is not None
    ra, dec, radius = client.last_cone_args
    assert ra == pytest.approx(1.0)
    assert dec == pytest.approx(1e-8)
    assert radius == pytest.approx(30.0)
