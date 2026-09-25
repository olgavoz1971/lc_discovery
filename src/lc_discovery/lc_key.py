"""Opaque lightcurve fetch handles (``lc_key``) shared across mission providers."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from skvo_veb.utils.my_tools import PipeException

logger = logging.getLogger(__name__)

LC_KEY_VERSION = 1


def encode_lc_key(mission_id: str, payload: dict[str, Any], *, version: int = LC_KEY_VERSION) -> str:
    """Builds a canonical JSON ``lc_key`` string for catalog rows and stores.

    Args:
        mission_id (str): Registered mission slug.
        payload (dict): Mission-private fetch parameters.
        version (int): Schema version for forward-compatible parsing.

    Returns:
        str: Stable JSON string with sorted object keys.
    """
    document = {
        "mission_id": mission_id,
        "v": version,
        "payload": payload,
    }
    return json.dumps(document, sort_keys=True, separators=(",", ":"))


def decode_lc_key(lc_key: str) -> dict[str, Any]:
    """Parses an ``lc_key`` JSON document.

    Args:
        lc_key (str): Serialised key from a catalog row or store.

    Returns:
        dict: Parsed document with ``mission_id``, ``v``, and ``payload``.

    Raises:
        PipeException: If the key is missing, malformed, or incomplete.
    """
    if not lc_key or not str(lc_key).strip():
        raise PipeException("Lightcurve key is empty.")

    try:
        document = json.loads(lc_key)
    except json.JSONDecodeError as exc:
        raise PipeException(f"Invalid lightcurve key JSON: {exc}") from exc

    if not isinstance(document, dict):
        raise PipeException("Lightcurve key must decode to a JSON object.")

    mission_id = document.get("mission_id")
    version = document.get("v")
    payload = document.get("payload")

    if not mission_id or not isinstance(mission_id, str):
        raise PipeException("Lightcurve key is missing mission_id.")
    if version != LC_KEY_VERSION:
        raise PipeException(f"Unsupported lightcurve key version: {version!r}.")
    if not isinstance(payload, dict):
        raise PipeException("Lightcurve key payload must be a JSON object.")

    return document


def validate_lc_key(lc_key: str, *, mission_id: str | None = None) -> bool:
    """Checks whether an ``lc_key`` is syntactically valid for a mission.

    Args:
        lc_key (str): Serialised key to validate.
        mission_id (str, optional): Expected mission slug. When set, must match.

    Returns:
        bool: True when the key parses and optional mission check passes.
    """
    try:
        document = decode_lc_key(lc_key)
    except PipeException:
        return False
    if mission_id is not None and document["mission_id"] != mission_id:
        return False
    return True


def cache_key(lc_key: str) -> str:
    """Derives a normalised cache hash for fetch-layer storage.

    Args:
        lc_key (str): Canonical serialised key.

    Returns:
        str: Hex digest suitable for shared disk cache filenames.
    """
    document = decode_lc_key(lc_key)
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
