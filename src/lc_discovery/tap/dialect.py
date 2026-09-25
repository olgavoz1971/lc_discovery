"""TAP query-language dialect identifiers (LANG parameter values)."""

from __future__ import annotations

from enum import Enum


class TapQueryDialect(str, Enum):
    """Supported TAP ``LANG`` values for ADQL dialect selection.

    Values follow TAP 1.1: ``ADQL`` or ``ADQL-<major>.<minor>``.
    """

    ADQL = "ADQL"
    ADQL_2_0 = "ADQL-2.0"
    ADQL_2_1 = "ADQL-2.1"
