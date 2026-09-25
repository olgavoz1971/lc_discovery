"""Filesystem-safe names for issued products."""

from __future__ import annotations

import re


def sanitize_filename(name: str) -> str:
    """Returns a filesystem-safe stem from a label.

    Args:
        name (str): Raw title or label text.

    Returns:
        str: Sanitised filename stem.
    """
    without_parens = re.sub(r"[()]", "", name)
    cleaned = re.sub(r'[<>:"/\\|?*,= \-]', "_", without_parens)
    cleaned = cleaned.replace("\u2014", "_").replace("\u2013", "_")
    return re.sub(r"_+", "_", cleaned)
