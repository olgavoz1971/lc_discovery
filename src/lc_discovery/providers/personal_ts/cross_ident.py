"""Cross-identification lookup against ``personal.objects``."""

from __future__ import annotations

import logging
import re

from lc_discovery.providers.personal_ts import config
from lc_discovery.tap.client import run_tap_sync_query
from lc_discovery.shared.tap_ssa_row import row_value

logger = logging.getLogger(__name__)

_IDENTIFIER_SPLIT = re.compile(r"\s*;\s*")


def normalize_alias_for_compare(text: str) -> str:
    """Normalises an alias token for case-insensitive cross-ident comparison.

    Args:
        text (str): Raw alias or identifier token.

    Returns:
        str: Collapsed, lower-case comparison key.
    """
    collapsed = re.sub(r"\s+", " ", str(text or "").strip())
    return collapsed.casefold()


def identifier_tokens(identifiers: str | None) -> list[str]:
    """Splits a semicolon-separated ``identifiers`` field into alias tokens.

    Args:
        identifiers (str, optional): Raw ``personal.objects.identifiers`` value.

    Returns:
        list[str]: Non-empty alias tokens.
    """
    if not identifiers:
        return []
    return [
        token.strip()
        for token in _IDENTIFIER_SPLIT.split(str(identifiers))
        if token.strip()
    ]


def alias_matches_identifiers(alias: str, identifiers: str | None) -> bool:
    """Checks whether ``alias`` matches one semicolon-separated identifier token.

    Args:
        alias (str): User-supplied alias or target name.
        identifiers (str, optional): Raw ``personal.objects.identifiers`` value.

    Returns:
        bool: True when ``alias`` equals a token after normalisation.
    """
    alias_key = normalize_alias_for_compare(alias)
    if not alias_key:
        return False
    return any(
        normalize_alias_for_compare(token) == alias_key
        for token in identifier_tokens(identifiers)
    )


def lookup_object_id_by_object_id(object_id: str) -> str | None:
    """Returns ``object_id`` when the row exists in ``personal.objects``.

    Args:
        object_id (str): Personal archive object identifier.

    Returns:
        str or None: Confirmed ``object_id`` when present in the objects table.
    """
    candidate = str(object_id or "").strip()
    if not candidate:
        return None
    table = run_tap_sync_query(
        config.TAP_URL,
        config.adql_objects_by_object_id(candidate),
        dialect=config.TAP_QUERY_DIALECT,
    )
    if len(table) == 0:
        return None
    resolved = row_value(table[0], "object_id")
    return str(resolved).strip() if resolved else None


def lookup_object_id_by_alias(alias: str) -> tuple[str, str] | None:
    """Resolves a user alias to ``object_id`` via ``personal.objects.identifiers``.

    Args:
        alias (str): User target name or cross-ident alias.

    Returns:
        tuple[str, str] or None: ``(object_id, matched_label)`` when recognised.
    """
    query_alias = str(alias or "").strip()
    if not query_alias:
        return None

    table = run_tap_sync_query(
        config.TAP_URL,
        config.adql_objects_by_identifier_substring(query_alias),
        dialect=config.TAP_QUERY_DIALECT,
    )
    for row in table:
        identifiers = row_value(row, "identifiers")
        if not alias_matches_identifiers(query_alias, identifiers):
            continue
        object_id = row_value(row, "object_id")
        if not object_id:
            continue
        resolved_id = str(object_id).strip()
        logger.info(
            "%s cross-ident matched alias=%r object_id=%r",
            config.DISPLAY_NAME,
            query_alias,
            resolved_id,
        )
        return resolved_id, query_alias
    return None
