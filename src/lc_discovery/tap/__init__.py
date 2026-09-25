"""Generic TAP query transport for lightcurve discovery providers."""

from lc_discovery.tap.client import run_tap_sync_query
from lc_discovery.tap.dialect import TapQueryDialect

__all__ = ["TapQueryDialect", "run_tap_sync_query"]
