"""Coverage of the mission as published in the VO Registry (stored once).

Record: ivo://astro.upjs/personal/q/ssa
Asked: http://reg.g-vo.org/tap (RegTAP), 2026-10-16.
Written by tools/fetch_registry_coverage.py; do not edit by hand. Time limits are
rounded outward to whole MJD days; spectral limits are as published (joules).
"""

REGISTRY_SPATIAL_MOC = (
    "6/5728-5730 11319 11325 11362 14209 14211-14212 18882 18888-18889 30116-30117 30119"
)

REGISTRY_TEMPORAL = ((36804.0, 59496.0),)

REGISTRY_SPECTRAL = ((2.1670317421420537e-19, 7.094449457398465e-19),)
