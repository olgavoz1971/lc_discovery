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

- `list_missions()` returns descriptors (with a human-readable `description`) and capability flags. It does not return a provider. To answer "which sources exist", read each `description`; open `docs/providers/<mission_id>.md` only for details. Text marked `TO CONFIRM` is unverified: say so to the user. The description ends with a `Search row columns:` paragraph; read it (see "What a search row tells you").
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
2. If the mission does not recognise the name, ask Simbad (astroquery or pyvo; the package core does not do it). You may use the helper `scripts/simbad_resolve.py` (`resolve_simbad_name(name)`; extra `scripts`); it returns the main id, the identifier list and the position, and raises `SimbadNotResolvedError` for an unknown name without any fallback. Keep the identifier list and the coordinates.
3. Call `archive_id_from_identifiers(mission, identifiers, ...)`. It picks the mission's id from the Simbad list. The line "Id lookup" in the mission `description` says which Simbad identifier it uses.
4. If there is still no id (or the description says Simbad does not list it), use a cone search at the Simbad position, only where `supports_cone_search` is true. Say that this is a position match and may include neighbouring stars.

Tell the user which route found each result.

### Variable stars that Simbad does not know

Some variable stars have a designation Simbad cannot resolve (for example `TCP J23580961+5502508`, or recent discoveries). If step 2 gives no result for a variable star, ask the AAVSO VSX index before giving up. The package provides a helper that you can run or copy: `scripts/vsx_resolve.py` (not public API, not imported by the package).

```bash
python scripts/vsx_resolve.py "TCP J23580961+5502508"   # prints the VSX record as JSON
```

What it does: one request to `https://vsx.aavso.org/index.php?view=api.object&ident=<name>`, XML answer, returns the VSX name, J2000 position, variability type, period, epoch and magnitude range. An unknown name raises `VsxNotResolvedError`; tell the user the name is not in VSX either and stop, do not guess a position.

Then continue like this:
1. **Get a Simbad name from the position.** Run `find_simbad_objects(ra, dec, radius_arcsec=5)` from `scripts/simbad_resolve.py` (or your own Simbad cone search) at the VSX RA and Dec. It returns every object inside the radius, nearest first, with separations, main ids and identifier lists; it fails if there is none, or if there are more than `max_candidates` (reduce the radius). Take the `main_id` and the identifier list of the chosen object. For the example the answer is `Gaia DR3 1993876650919517440`.
2. Pass the identifiers to `archive_id_from_identifiers(...)` as in step 3 above, or use a cone search on the missions at the VSX position (step 4 above).
3. **Zero or several Simbad objects:** show the candidates with their separations and ask the user which one is meant. Do not pick silently, especially in crowded fields.
4. **Report to the user:** that the position came from VSX (not Simbad), the VSX name, type and period, and the separation of the Simbad match. VSX positions can be less accurate than Gaia, so say so when a cone search finds nothing.

The `identifiers` of a candidate (`result.identifiers`), with `result.main_id`, `result.ra_deg` and `result.dec_deg`, are the arguments of `archive_id_from_identifiers`.

Rules for the VSX server: one request at a time, no loops over long lists, no personal contact address in requests. The list of other names on the VSX web page is not read by the helper; do not scrape it.

## What a search row tells you

`search` returns one table row per light curve, and **every column in it is meaningful**. Many are interesting to the researcher on their own: the filter, the mean magnitude, the number of points, the time span, the object class (for example `EB*` or `ECL`), the period, the survey, the distance from the search position, and notes from the provider. Do not look only at `lc_key`.

1. **Read the columns of the table you got** (`catalog.colnames`) and look at the values before you decide anything. Columns differ between missions; an empty (masked) value means "not known at search time", not "zero".
2. **Read the paragraph `Search row columns:` in the mission `description`** (from `list_missions()`). It says which columns that mission fills, what they mean there (for example "mag is the mean G magnitude, on the G row only") and how many rows one star gives.
3. **Show the researcher all the columns that carry information.** The search result already holds only the columns that matter, so do not choose among them yourself.
   - Show every column that has at least one value, in the table order, except `lc_key` (an opaque handle for the software; keep it in the saved file).
   - A column that is empty in every row may be left out of the display; say so in one line ("not filled for this mission: n_points, mag").
   - A column with the same value in every row (for example `survey` or `filter_identifier`) may be stated once above the table.
   - Do not rank columns or recommend a product unless the user asks. Show the facts.
   - Your own summary must not reduce the columns to a count: a number of "products" next to a short list of sectors cannot be checked by the user. Keep the columns that tell the light curves apart (for TESS: sector, exposure time, author).
4. **Answer from the table before fetching.** Questions such as "how many points", "which filter", "how bright", "which is the longest" are often answered by the table. Fetch only what the table cannot answer (for example the real time span when `t_min` and `t_max` are empty), and tell the user why you fetch. "Longest" can mean most points (`n_points`) or longest time span (`t_max - t_min`); say which you used, or ask.
5. **Do not mix columns across rows.** One row is one light curve in one filter. A value such as `mag` may belong to one band only.
6. **Keep the search result.** Save every search table to a file and tell the user the path. Use ECSV (`catalog.write(path, format="ascii.ecsv")`): it keeps types, masked values and `meta` (including the truncation flags). A folder such as `lc_discovery_results/` in the user's working directory is a good place, with a name that says the mission and the target. When the user asks something more about a result, **read the saved file; do not search again** (searches can be slow). Search again only if the user asks for fresh data or a different query. Keep the whole table available, not only your summary of it.
7. **Many targets.** For a list of stars, one table of hundreds of rows is unreadable, and a table of counts is too thin. Give one line per target that still uses the columns (for example: name and archive id, number of rows, the distinct values of the columns that separate light curves, the time span as calendar dates from `t_min` and `t_max`, filled `mag`/`n_points`), mark targets with no rows explicitly ("no TESS light curve found"), and offer the full per-row table from the saved file on request. Example for TESS, after searching each star by its TIC (the values are illustrative only): `AR Lac | TIC 420116962 | 16 rows | sectors 16, 56, 76, 83 | exposure 120 s, 200 s, 600 s | authors SPOC, QLP, TESS-SPOC, TARS | 2019-09 to 2024-09`. Build such lines from the table, never from memory.

## Respect the metadata of the product

The package issues a calibrated, self-describing light curve. Read its metadata and use it. Never hardcode or assume an offset, a time scale, a flux zero point or a unit, unless the user explicitly asks you to. Tell the user which time system and photometric system you used.

- **`TIMESYS`**: `timescale` (for example TDB, TCB, UTC), `refposition` (for example BARYCENTER) and `timeorigin`. A time value is relative to `timeorigin`: the values in the column are days since that Julian Date (a `timeorigin` of 2400000.5 means MJD, 2457000 means BTJD). Different missions use different origins; read it for each light curve.
- **`COOSYS`**: the reference frame and epoch of the coordinates.
- **`PHOTCAL`**: filter, magnitude system and zero point of each photometry column. The magnitude system need not be Pogson, so do not write magnitude-flux formulae yourself; the calibration says how to convert.
- Units and UCDs on the FIELDs tell which column is time, magnitude, flux or error. Do not guess them from column names.

Recommended, not required: the `volightcurve` package (https://github.com/olgavoz1971/volightcurve) reads such a VOTable with `read_lightcurve`, and returns the table, `timesys`, `photdms` (filter and `PhotCal`) and the column-discovery helpers (`get_time_colnames`, `get_flux_colnames`, ...). `PhotCal.mag_to_flux` and `flux_to_mag` do the conversions and raise `PhotCalError` instead of inventing a zero point. `volightcurve` has its own skill under `.cursor/skills/volightcurve/`. Without it, read the same elements from the VOTable with `astropy.io.votable` and report what you found.

## Folded light curves: period and epoch

When the user asks for a folded (phase) light curve, you need a period and, for a phase zero point, an epoch.

1. **Look in the fetched VOTable first.** Some products carry the table PARAMs `period` (unit `d`, UCD `src.var;time.period`) and `epoch` (UCD `time.epoch`). Where they come from depends on the mission (for example ASAS-SN reads them from its own copy of the VSX data, Gaia from the variability tables, TESS only for the TARS author). An empty or zero epoch means "not given".
2. **If the period is missing, look it up in VSX.** Use `scripts/vsx_resolve.py` (section "Variable stars that Simbad does not know" above): `period_days`, `epoch_jd` and `variability_type` are in its record. Do not invent a period, and do not estimate one from the data unless the user asks for it. If VSX has no period either, tell the user and ask.
3. **The epoch is optional.** Without it, fold with an arbitrary zero point (for example the first observation) and say so.
4. **ALWAYS tell the user explicitly where each element came from**: "period 0.9 d from the VOTable (author TARS)", "epoch from VSX, JD 24xxxxx, VSX type EA", or "epoch not available; zero phase is the first point". If the values differ between sources, show both and say which one you used and why.
5. **Time system of the epoch.** VSX documents its epoch as HJD (VizieR B/vsx), but old entries come from the GCVS and old papers in JD, some papers use BJD, and the VSX web service returns a bare number with no label. Take the time system of the light curve from its `TIMESYS` (see "Respect the metadata of the product"), convert the VSX epoch to that convention with `astropy.time`, and tell the user the assumption ("VSX epoch, documented as HJD, treated as the same system as the light curve"). The difference between HJD, BJD and JD is at most about 8 minutes: irrelevant for a plot, relevant for precise timing.
6. **What the epoch means.** For most pulsating variables it marks a maximum, for eclipsing, ellipsoidal, RV Tau and dark-spotted stars a minimum (check `variability_type`); say which one you assume. Do not test the epoch against the data: periods change and other effects act, so for many variable stars the epoch does not land precisely on an extremum at every cycle, and such a check usually fails. If the folded curve looks shifted, report it to the user; do not tune the epoch silently.

## Plotting a fetched light curve (advice)

The package only returns the VOTable bytes; plotting is yours. For photometry use points (markers, no connecting lines), magnitudes with the axis **inverted**, and a calendar date axis (convert MJD with `astropy.time.Time(mjd, format="mjd").datetime`, or `.plot_date`/ISO strings). Put the filter name, the object and the mission in the title; take the filter from the row's `filter_name` or from the VOTable photcal metadata. Drop non-finite points and say how many were dropped. A scatter plot made with matplotlib suits irregular, gappy data better than an interactive line chart.

## Time windows

Where `supports_discovery_time_filter` is true, pass `time_start_mjd` and `time_end_mjd`; the catalogue is filtered at search time (fast). A product is kept when its time span (`t_min` to `t_max`) overlaps the window. That makes a point inside the window likely, not certain: a product with a gap over the whole window still passes. Say so if the user needs a guarantee.

Where it is false, the search ignores the window and does not know the coverage. See the next section for what to do with those missions.

## Searching several missions

A researcher asks "all light curves of this star" or "all that could have a point in the first half of 2020". The goal is: **return every light curve that could possibly contain at least one point in the requested window.** It is better to return extra candidates than to miss data. Never throw a source away by default.

Rules:

1. **Do not drop a mission silently.** "Not supported" is not "no data".
   - A mission that cannot do the requested search kind (for example no name search, no cone search) or cannot filter by time: tell the user which one and why, and **ask whether to use it anyway** (for example by another search kind, or without the window).
   - A mission that is known to have no data for the request is the only one that may be skipped, and only when the descriptor states it explicitly (see "Coverage of a mission" below). Say that you skipped it and give the reason.
2. **Time window.** Pass `time_start_mjd` and `time_end_mjd` only where `supports_discovery_time_filter` is true. For the other missions search without the window and mark each row **unknown coverage** (or use the row's `t_min` / `t_max` if they are filled). These are possible sources, not confirmed ones.
3. **Unknown coverage rows.** Some rows have no `t_min` / `t_max` (for example `gaia_dr3_aip`, which learns the coverage only after fetch). Keep them as "unknown". **Do not fetch light curves in bulk to find out.** Fetching can be heavy in network traffic and in time. If in doubt, tell the user that and ask which rows to fetch, or whether to fetch many.
4. **Errors do not stop the run.** If one mission raises (service down, bad input), keep going with the others, and list at the end: mission, error message as it came, and that its results are missing.
5. **Same data in several missions.** Group the missions by `data_group`; do not ask all of them.
   - Ask the non-subset members in `group_rank` order (lowest first). Move to the next one only if the first **fails** or does **not support** the requested search kind (say which). An empty answer is an answer: do not ask the next one because of it. Say which mission answered.
   - A member with `is_subset` true holds only part of the data (`subset_description` says what). Tell the user. By default ask it **last**, and skip it when a non-subset member of its group answered (say that you skipped it and why). If no non-subset member answered, warn the user and ask it anyway.
   - If the user asks explicitly for what the subset holds (for example eclipsing binaries), **suggest** starting with that subset. Do not limit the search to it: if it fails or returns nothing, go on with the non-subset members and say so.
   - **Report subset-only results.** If rows come from a subset alone, tell the user the result covers only the subset and may be incomplete. In a cone search this matters most: neighbouring stars outside the subset are missing.
   - If a fetch fails, report the error. You may suggest repeating the search on another member of the group (its `lc_key` values differ), but do not do it silently.
   - If rows of one group arrive together, remove duplicates by archive id.
6. **Truncation.** Read `catalog.meta.get("discovery_may_be_truncated")` after each search. If true, tell the user that the list may be incomplete (and show `catalog.meta.get("discovery_truncation_detail")` if present) and offer a narrower search.
7. **Coverage.** Read `mission.coverage` of every mission before searching (see "Coverage of a mission" below). Skip a mission only if its coverage **explicitly** shows that the requested data cannot be there, and say which part (space, time or spectrum) and why. If a part is `None`, the coverage is unknown: do not skip, and warn the user.

Report to the user: the rows found per mission, which rows are "unknown coverage", which missions were skipped or failed (with reasons), and whether any list may be truncated.

## Coverage of a mission

`list_missions()` returns `MissionDescriptor.coverage` (`MissionCoverage`), built like the VO Registry coverage (IVOA VODataService 1.2, section 3.2; RegTAP 1.2; MOC 2.0). It describes the **whole mission**, not one star: "TESS covers the whole sky" does not mean that this star was observed.

| Part | Form | How to test it |
|---|---|---|
| `spatial` | MOC string (IVOA ASCII; all sky is `0/0-11`), or `None` | With a MOC library (for example MOCpy: `MOC.from_string(text).contains_lonlat(ra, dec)`; ICRS, degrees). The package does not need MOCpy; if it is not installed, treat space as unknown. |
| `temporal` | tuple of `(start, end)` MJD (TDB) intervals, whole days, or `None` | The window `[a, b]` overlaps an interval if `end > a` and `start < b`. An end of `100000` means "still running". |
| `spectral` | tuple of `(low, high)` energy limits in joules, or `None` | Convert a wavelength with `astropy.units.spectral()`. Rough values only. |
| `waveband` | tuple of Registry terms (`("Optical",)`) | Compare with the band the user wants. |

Rules:
- Test only the parts the user asked about (a sky position, a time window, a band). Skip the mission if one tested part is known and the request is entirely outside it.
- The values are approximate on purpose: MOCs are coarse (order 6, about 1 degree, so the edge may reach a little beyond the real one), spectral limits are rough. Treat a request near an edge as inside.
- `None` never skips. Tell the user which missions have unknown coverage in the requested part.
- Tell the user about every skip: mission, part, and the coverage value that excluded it.
- Coverage does not replace the search. A mission that passes the test may still return nothing.


Example: all light curves of one position that could overlap a window.

```python
from lc_discovery import list_missions, search

ra, dec, radius = 11.5, 41.0, 10.0
start, end = 58849.0, 59031.0                  # MJD, first half of 2020

groups = {}
for m in list_missions():                      # one entry per data group
    groups.setdefault(m.data_group, []).append(m)

found, asked_user, failed, truncated, skipped = {}, [], {}, [], []
for members in groups.values():
    full = sorted((m for m in members if not m.is_subset), key=lambda m: m.group_rank)
    subsets = [m for m in members if m.is_subset]
    answered = False
    for m in full + subsets:                   # non-subset by rank, subsets last
        if answered:                           # say it, never drop silently
            skipped.append((m.mission_id, "same data already answered by a higher rank"))
            continue
        caps = m.capabilities
        if not caps.supports_cone_search:      # unsupported is not "no data": tell the user
            asked_user.append((m.mission_id, "no cone search; try name or id?"))
            continue
        kwargs = dict(ra_deg=ra, dec_deg=dec, radius_arcsec=radius)
        window_known = caps.supports_discovery_time_filter
        if window_known:
            kwargs.update(time_start_mjd=start, time_end_mjd=end)
        try:
            catalog = search(m.mission_id, **kwargs)
        except ValueError as exc:              # keep going, report at the end
            failed[m.mission_id] = str(exc)
            continue
        answered = True                        # empty is an answer; next ones are skipped
        if catalog.meta.get("discovery_may_be_truncated"):
            truncated.append(m.mission_id)
        found[m.mission_id] = (catalog, window_known)

# Report: rows per mission; for window_known False say "coverage unknown,
# possible source only"; rows from a subset alone say "subset only, may be
# incomplete" (m.subset_description); then asked_user, skipped, failed, truncated.
```

Do not fetch any of these rows in the loop. Fetch only what the user chooses.

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

If the ASAS-SN provider raises "pyasassn is required", install the maintainer's fork of Sky Patrol (`pip install -e ".[asassn]"` in the package, or `pip install "skypatrol @ git+https://github.com/olgavoz1971/skypatrol.git@master"`). The upstream package is not enough. A `ConnectionError` saying the archive "reports no lightcurve servers" means the ASAS-SN archive itself is down; tell the user and try again later.

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
