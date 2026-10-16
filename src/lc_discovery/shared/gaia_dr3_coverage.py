"""Coverage shared by the Gaia DR3 epoch-photometry missions (ARI, AIP and VEB)."""

from __future__ import annotations

from lc_discovery.coverage import ALL_SKY_MOC, WAVEBAND_OPTICAL, MissionCoverage

# Time: Gaia DR3 observing period, 25 July 2014 to 28 May 2017 (MJD 56863 to the end of that
# day, 57902); the same interval, rounded outward, as the Registry record below.
# Spectral: the G, BP and RP range as published in the VO Registry record
# ivo://astro.upjs/gaiadr3_eb/q/ssa (RegTAP http://reg.g-vo.org/tap, 2026-10-16), in joules.
# The missions serve the same filters, so they share it. Space is all sky for all three.
GAIA_DR3_EPOCH_PHOTOMETRY_COVERAGE = MissionCoverage(
    spatial=ALL_SKY_MOC,
    temporal=((56863.0, 57902.0),),
    spectral=((1.897273927221733e-19, 6.015887105726923e-19),),
    waveband=WAVEBAND_OPTICAL,
)
