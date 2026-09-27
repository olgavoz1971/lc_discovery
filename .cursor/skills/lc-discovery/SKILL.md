---
name: lc-discovery
description: >-
  Public contract of the lc_discovery package: list_missions, search,
  resolve_target, archive_id_from_identifiers, fetch (VOTable bytes). Use when
  calling discovery from an app or agent, changing api.py or registry, writing
  package tests, or discussing fetch vs Astropy Table / VOTableFile.
---

# lc_discovery public API

Read `README.md` first, then `docs/schema.md`.

## Calls

Applications import only:

```python
from lc_discovery import list_missions, search, fetch, resolve_target, archive_id_from_identifiers
```

- `list_missions()` returns descriptors and capability flags. It does not return a provider.
- `search(mission_id, ...)` returns an Astropy catalogue `Table` with opaque `lc_key`.
- `resolve_target(mission_id, name)` returns an archive-id match or `None`.
- `archive_id_from_identifiers(mission_id, identifiers, ...)` picks an archive id from Simbad-style strings.
- `fetch(lc_key)` returns **bytes** (enriched VOTable). Not `Table`, not `VOLightCurve`.

Do not call `get_provider`, `fetch_lightcurve`, `enrich_votable`, or `decode_lc_key` from application code.

Search kinds: cone (`ra_deg`, `dec_deg`, `radius_arcsec`), name (`object_name`), archive id (`archive_id`), optional MJD window where `supports_discovery_time_filter` is true.

## Fetch product

The issued product is the VOTable document (photcal `GROUP`, `TIMESYS`, `COOSYS`, `PARAM` utypes). `Table.read(..., format="votable")` loads **columns and rows only**. Example in `README.md` under “Read the points as an Astropy Table”.

## Tests

Package tests live in `tests/` and import `lc_discovery` only. No `skvo_veb`, Aladin, CurveDash, or `volightcurve`. Dash tests stay in the application repository.

## Behaviour

Fail fast. No silent fallbacks. No invented photometry-filter identifiers or zero points. Enrichment changes belong in `docs/providers/<mission>.md`. User-facing strings: British English.
