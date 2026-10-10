---
name: lc-discovery
description: >-
  Public contract of the lc_discovery package: list_missions, search,
  resolve_target, archive_id_from_identifiers, fetch (VOTable bytes), purge_cache. Use when
  calling discovery from an app or agent, changing api.py or registry, writing
  package tests, or discussing fetch vs Astropy Table / VOTableFile.
---

# lc_discovery public API

Read `README.md` first, then `docs/schema.md`.

## Calls

Applications import only:

```python
from lc_discovery import (
    list_missions, search, fetch, purge_cache, resolve_target, archive_id_from_identifiers,
)
```

- `list_missions()` returns descriptors (with a human-readable `description`) and capability flags. It does not return a provider. To answer "which sources exist", read each `description`; open `docs/providers/<mission_id>.md` only for details. Text marked `TO CONFIRM` is unverified: say so to the user.
- `search(mission_id, ...)` returns an Astropy catalogue `Table` with opaque `lc_key`.
- `resolve_target(mission_id, name)` returns an archive-id match or `None`.
- `archive_id_from_identifiers(mission_id, identifiers, ...)` picks an archive id from Simbad-style strings.
- `fetch(lc_key)` returns **bytes** (enriched VOTable). Not a `Table`, not a reader object.
- `purge_cache(lc_key)` deletes the locally cached product of that one key (`True` if a file was deleted). Only where `capabilities.supports_cache_purge` is true; otherwise `ValueError`. `fetch(lc_key, force_refresh=True)` purges and downloads again.

Never clear a whole cache directory. Refresh one product with `purge_cache` or `force_refresh`.

Do not call `get_provider`, `fetch_lightcurve`, `enrich_votable`, or `decode_lc_key` from application code.

Search kinds: cone (`ra_deg`, `dec_deg`, `radius_arcsec`), name (`object_name`), archive id (`archive_id`), optional MJD window where `supports_discovery_time_filter` is true.

## Finding an object (advice, not a fixed algorithm)

A user gives a name such as `AA And`. Suggested order for each mission:

1. Try the mission directly: `resolve_target(mission, name)` (it recognises its own id spellings, such as `TIC 123` or a Gaia number), then `search(mission, archive_id=match.archive_id)`.
2. If the mission does not recognise the name, ask Simbad yourself (astroquery or pyvo; this package does not do it). Keep the identifier list and the coordinates.
3. Call `archive_id_from_identifiers(mission, identifiers, ...)`. It picks the mission's id from the Simbad list. The line "Id lookup" in the mission `description` says which Simbad identifier it uses.
4. If there is still no id (or the description says Simbad does not list it), use a cone search at the Simbad position, only where `supports_cone_search` is true. Say that this is a position match and may include neighbouring stars.

Tell the user which route found each result.

## Time windows

Where `supports_discovery_time_filter` is true, pass `time_start_mjd` and `time_end_mjd`; the catalogue is filtered at search time (fast). A product is kept when its time span (`t_min` to `t_max`) overlaps the window. That makes a point inside the window likely, not certain: a product with a gap over the whole window still passes. Say so if the user needs a guarantee.

Where it is false, the search ignores the window and does not know the coverage. If the user wants a specific time overlap:

- Warn that these missions cannot filter by time at the search step.
- List them as possible sources of an overlapping light curve, not as confirmed ones.
- Say that checking means fetching each light curve, which is slow. Do not do this for a long list of rows; offer to fetch a few chosen ones.

## Worked example

Find a light curve by name, fetch it, read its points.

```python
import io
from astropy.table import Table
from lc_discovery import list_missions, search, resolve_target, fetch

mission = "ogle_ocvs"
caps = {m.mission_id: m.capabilities for m in list_missions()}[mission]
assert caps.supports_name_resolve            # check before choosing a search kind

catalog = search(mission, object_name="OGLE-LMC-RRLYR-13820")
if len(catalog) == 0:                        # empty is a normal answer, not an error
    match = resolve_target(mission, "OGLE-LMC-RRLYR-13820")
    if match is None:
        raise SystemExit("Mission does not know this name.")
    catalog = search(mission, archive_id=match.archive_id)

lc_key = catalog["lc_key"][0]                # opaque; never parse it
payload = fetch(lc_key)                      # bytes: the issued VOTable
points = Table.read(io.BytesIO(payload), format="votable")   # points only
```

`points` has columns and rows but not the PhotCal groups, FIELDrefs or
TIMESYS. To keep the whole document, keep the bytes.

Cone search needs `supports_cone_search`:
`search(mission, ra_deg=..., dec_deg=..., radius_arcsec=...)`.

## Errors

Every failure is a `ValueError` whose message names the mission and the
cause. Show it as is; do not replace it with a guess. An empty catalogue
is an empty `Table`, not an error. If a search kind is not supported by the
mission, the call raises; read `capabilities` first.

## Fetch product

The issued product is the VOTable document (photcal `GROUP`, `TIMESYS`, `COOSYS`, `PARAM` utypes). `Table.read(..., format="votable")` loads **columns and rows only**. Example in `README.md` under “Read the points as an Astropy Table”.

## Tests

Package tests live in `tests/` and import `lc_discovery` only. They use mocks, not the network. A test that really calls an archive must carry `@pytest.mark.integration`; the default run is `pytest -m "not integration"`.

## Behaviour

Fail fast. No silent fallbacks. No invented photometry-filter identifiers or zero points. Enrichment changes belong in `docs/providers/<mission>.md`. User-facing strings: British English.
