# Mission lightcurve providers: architecture guide

**Audience:** maintainers and AI agents who change or add a mission plugin.

**Checklist for a new plugin:** [adding_a_lightcurve_provider.md](adding_a_lightcurve_provider.md).

**Public calls, search kinds and examples:** [README.md](../README.md).

**Issued product contract:** [schema.md](schema.md). **Per-mission notes:** [providers/](providers/).

This package is independent of any application. It never imports an interface framework, a plotting library or an
application data model.

**Scope:** TESS pixel workflows (cutouts, target pixel files) are not part
of this package. TESS archive pipeline light curves (MAST products) are the
`tess` plugin.

---

## 1. Goal

Give any caller (an application, a notebook, a script, an agent) one way to:

1. Pick one mission.
2. Search its catalogue by cone, by name or by archive id.
3. Get a standard catalogue table where one row is one light curve.
4. Fetch one light curve as a calibrated VOTable document.

Mission-specific remote access (Sky Patrol, TAP, IRSA, datalink, MAST) lives
inside the plugin and is usable without any application.

## 2. Core design decision: fetch returns VOTable bytes

```text
MissionProvider.fetch_lightcurve() -> VOTable bytes
Public API:                          fetch(lc_key) -> the same bytes
```

The caller parses the bytes with the tools of its choice (Astropy, GAVO,
a VO-light-curve reader). Plugins do not choose one working photometry column
for a plotter and do not return a table object, because a table object drops
the calibration groups (see the README).

| Layer | Module | Responsibility |
|-------|--------|----------------|
| Mission adapters | `src/lc_discovery/providers/` | Remote query and issued VOTable bytes |
| Public API | `src/lc_discovery/api.py` | `list_missions`, `search`, `resolve_target`, `archive_id_from_identifiers`, `fetch`, `purge_cache` |
| Tests | `tests/` | Catalogue contract and VOTable XML |

## 3. Mission provider API (ABC)

Location: `src/lc_discovery/base.py`.

This is a registry of adapters that implement one provider interface. Each
mission package turns an archive API into the standard catalogue and the
issued VOTable. The registry picks which adapter runs.

Keep the base class thin. Shared logic belongs in helpers.

### 3.1 Identity (class-level)

| Attribute | Example | Purpose |
|-----------|---------|---------|
| `mission_id` | `"asassn"` | Stable slug for the registry and `lc_key` |
| `display_name` | `"ASAS-SN Sky Patrol"` | Label for a mission selector |
| `export_profile` | `"asassn"` | Name of the export profile for this mission |
| `capabilities` | flags struct | What the mission supports |

Capability flags:

- `supports_cone_search`: RA/Dec and radius.
- `supports_id_lookup`: direct archive query by mission-native id (a Gaia
  `source_id`, a TIC). It does not mean "resolve the id to coordinates and
  run a cone search".
- `supports_name_resolve`: the mission accepts a generic `object_name`.
- `supports_force_refresh`: `fetch(..., force_refresh=True)` discards the
  local product and downloads it again.
- `supports_cache_purge`: `purge_cache(lc_key)` can delete the locally
  cached product (see section 9).
- `provides_catalog_epoch_period`: catalogue rows can carry epoch and period.

### 3.2 Required methods

`search_catalog(...)` is the discovery entry point. The provider decides which
arguments apply:

```python
search_catalog(
    *,
    ra_deg: float | None = None,
    dec_deg: float | None = None,
    radius_arcsec: float | None = None,
    object_name: str | None = None,
    archive_id: str | None = None,
    **mission_options,
) -> Table
```

| Call pattern | Provider behaviour |
|--------------|--------------------|
| `ra_deg`, `dec_deg`, `radius_arcsec` | Cone search when `supports_cone_search` |
| `object_name` | The provider parses the name or id (`Gaia DR3 123...`, `TIC ...`) and queries its archive. It does not convert an id to a cone search. |
| `archive_id` | Direct id lookup, no coordinates |

Only the plugin parses mission-specific formats (`Gaia DR3 ...`, `TIC ...`, KIC).

`fetch_lightcurve(lc_key, *, force_refresh=False) -> bytes` returns the
calibrated VOTable (TIMESYS, PhotCal GROUPs, FIELD UCDs). It is called when a
caller wants the light curve, not on search.

`purge_cached_product(lc_key) -> bool` deletes the locally cached product of one
light curve. The base class raises `ValueError`; a mission overrides it when
it keeps a local cache and sets `supports_cache_purge`.

### 3.3 Cross-identifier match (mission-specific id pick)

When a caller has a Simbad-style list of identifiers, the mission picks its own
id. The caller does not know Gaia from TIC formats.

```python
@dataclass
class MissionArchiveMatch:
    archive_id: str       # mission-native id (for example a Gaia source_id string)
    match_kind: str       # for example "gaia_source_id", "tic"
    matched_label: str    # readable label (for example "Gaia DR3 1791119426789765632")
```

```python
def pick_archive_id_from_simbad(self, simbad_result) -> MissionArchiveMatch | None:
    """Returns this mission's archive id from Simbad identifiers, or None."""
```

Public wrappers: `resolve_target(mission_id, name)` and
`archive_id_from_identifiers(mission_id, identifiers, ...)`. When a match is
found, call `search(..., archive_id=match.archive_id)`. Prefer a direct id
lookup over a cone search at the object's coordinates; use a cone search only
when no mission id is available.

### 3.4 Helpers

| Method | Purpose |
|--------|---------|
| `validate_lc_key(lc_key) -> bool` | Checks that a key belongs to this mission |
| `cache_key(lc_key) -> str` | Normalised SHA-256 hash of a key, for a caller's own cache |
| `default_search_radius_arcsec() -> float` | Mission default cone radius |

### 3.5 What providers must not do

- Return a table object or a reader object instead of bytes.
- Import an interface framework, a plotting library or an application package.
- Implement trimming, folding or export of the host.
- Collapse several archive flux columns to one default series.
- Call any host module to build the VOTable (build the XML in the plugin).

The caller's orchestration (name parsing, Simbad query, retry order) is
outside this package.

---

## 4. Standardised catalogue table (search results)

One row is one light curve, not one source. Example: ASAS-SN `V` and `g` give
two rows.

The table is an Astropy `Table` with enforced column names. Helpers live in
`src/lc_discovery/catalog_schema.py`: `empty_catalog_table()` and
`validate_catalog_table(t)`.

### 4.1 Required columns

| Column | Type | Description |
|--------|------|-------------|
| `distance_arcsec` | float | Separation from the search centre |
| `ra_deg` | float | ICRS right ascension (degrees) |
| `dec_deg` | float | ICRS declination (degrees) |
| `object_name` | str | Mission or database label |
| `filter_name` | str | Readable filter (for example `"ASAS-SN g"`) |
| `lc_key` | str | Opaque fetch handle (section 6) |

### 4.2 Optional columns (present, nullable)

| Column | Type | Description |
|--------|------|-------------|
| `filter_identifier` | str | FPS / IVOA filter id |
| `n_points` | int | Epoch count preview |
| `t_min` | float | Coverage start (MJD) |
| `t_max` | float | Coverage end (MJD) |
| `mag` | float | Catalogue magnitude if available |
| `object_class` | str | Classification when the archive supplies it |
| `survey` | str | Sub-survey or programme |
| `provider_note` | str | Extra context |
| `epoch` | float | Catalogue folding epoch (full JD) |
| `period` | float | Catalogue period (days) |

Never use `0` or `-2400000.5` as missing-value markers for epochs.

This optional list is closed. Do not add mission-specific names here.

### 4.3 Extra catalogue columns (locked)

Providers may declare extra display columns. Default: none. See
[schema.md](schema.md) (Catalogue extra columns).

- Declare `(field, header)` pairs on the provider.
- Put matching columns on the table. `validate_catalog_table` accepts those
  names only when they were declared, and rejects a clash with section 4.1 or 4.2
  names.
- Extra columns are not search filters and are not part of `lc_key`.

The flags `discovery_catalog_includes_object_class` and
`discovery_catalog_includes_n_points` remain for the core optional columns.
They are not a pattern for inventing mission flags.

---

## 5. Issued VOTable (fetch output)

`fetch` and `fetch_lightcurve` return bytes: a VOTable document.

Column names are not the contract. Roles are UCDs (`time.epoch`, `phot.flux`,
`phot.mag`, `stat.error;phot.flux`). Several flux, magnitude or background
columns are allowed. Each photometry column that has a PhotCal carries
`FIELD/@ref` to a PhotCal `GROUP` in the same file. Do not drop extra science
columns so that only one series remains.

### 5.1 Minimum invariants

**Time**
- At least one column with UCD `time.epoch`.
- `TIMESYS` with `timescale`, `refposition` and `timeorigin`.
- The time FIELD `ref` is that `TIMESYS/@ID`.

**Photometry**
- Keep the archive flux, background and error columns that exist.
- UCD `phot.flux` or `phot.mag` on photometry; `stat.error;...` on errors.
- PhotCal GROUP: `filterIdentifier`; zero points only when the provider note
  documents them; background columns get no magnitude zero point.

**Table PARAMs** (when available): `ra`, `dec`, `period`, `epoch`, and
pipeline or author metadata.

### 5.2 Tests

Assert the bytes: FIELD names, UCDs, TIMESYS, PhotCal PARAMs. Live archive calls
belong behind mocks, except tests marked `@pytest.mark.integration`.

---

## 6. `lc_key` format

An opaque handle stored in catalogue rows. It is JSON-serialisable and small.

```json
{
  "mission_id": "asassn",
  "v": 1,
  "payload": {
    "gaia_id": 1791119426789765632,
    "band": "g"
  }
}
```

Rules:
- Always include `mission_id` and the schema version `v`.
- `payload` is private to the mission (ids, band codes, tokens).
- Use stable JSON key ordering for hashing.
- Never include secrets or credentials.

Only the owning provider parses `payload`. Callers do not decode keys.

---

## 7. Registry

`registry.py` maps `mission_id` to a provider instance. It is the single
discovery point for callers.

```python
PROVIDERS: dict[str, MissionLightcurveProvider]

def get_provider(mission_id: str) -> MissionLightcurveProvider: ...
def list_missions() -> list[MissionDescriptor]: ...
```

Adding a mission:

1. Implement the provider in `src/lc_discovery/providers/<mission>/`.
2. Register it in `registry.py`.
3. Add tests under `tests/` (catalogue schema, `lc_key` round trip, fetch bytes).

---

## 8. Provider notes and shared post-processing

Per-mission discovery, retrieval and any calibration this code adds:
[providers/](providers/).

After each fetch, an error column with no photcal of its own is linked to the
photcal of the single matching magnitude or flux column
(`share_photcal_with_unlinked_errors`). An error column the archive already
linked is not changed. Several calibrated parents are left alone.

### ASAS-SN adapter

Package: `src/lc_discovery/providers/asassn/` (`AsassnProvider`, id `asassn`).

| Area | Behaviour |
|------|-----------|
| Discovery | `stellar_main` and `cols` (`asas_sn_id`, `ra_deg`, `dec_deg`, `pstarrs_g_mag`); cone, Gaia id or name; two candidate rows per source (`g`, `V`); `mag` on `g` only; shared `provider_note`; no time filter |
| Truncation | Cap source count (100) before doubling; entity label "ASAS-SN sources" |
| Fetch | `lc_key`: `asas_sn_id` and `band`; Sky Patrol `download=True`; empty band fails fast; epoch and period via `aavsovsx` ADQL at enrich |
| Cache | None |

---

## 9. Caching and refresh

The package keeps no cache of search results and no cache of issued VOTables.
A caller that wants one can key it by `provider.cache_key(lc_key)` (a hash of
the key); that is outside the package.

Where a mission keeps a local copy of the archive product, the package
exposes one common control:

| Call | Effect |
|------|--------|
| `fetch(lc_key, force_refresh=True)` | Discards the local product of that key and downloads it again, then issues the VOTable |
| `purge_cache(lc_key)` | Deletes the local product of that key only; the next `fetch` downloads again. Returns `True` when a file was deleted |

Both act on one product (one object, one sector, one author). Neither touches
the rest of the cache. A mission without a local product cache has
`supports_cache_purge` false, and `purge_cache` raises `ValueError`.

Missions with a local product cache today:

| Mission | Local product | Purge |
|---------|---------------|-------|
| `tess` | MAST FITS in the Lightkurve cache | Yes |
| `gaia_dr3_aip` | Prefetched epoch JSON per Gaia source (all bands) | Yes; removes all bands of that source |

---

## 10. Error handling

- Failures are `ValueError` with a message that names the mission and the
  cause, for example `"ASAS-SN: source not in Sky Patrol"`. The message is
  the interface: a caller shows it as is.
- An empty catalogue after a successful search is an empty table, not an
  exception.
- No silent fallbacks. A different path (for example a retry by main name) is
  a decision of the caller, who reports it.

---

## 11. Summary for agents

| Question | Answer |
|----------|--------|
| What is this architecture called? | Plugin registry (section 3) |
| Where do missions live? | `src/lc_discovery/providers/` |
| What does search return? | The standard catalogue table (section 4) |
| What does fetch return? | VOTable bytes (section 5) |
| How do I refresh one product? | `fetch(lc_key, force_refresh=True)` or `purge_cache(lc_key)` (section 9) |
| Gaia id lookup | Direct archive query in the provider, not id to coordinates to cone |
| Where is the issued-product contract? | `docs/schema.md` and section 5 |
| Is the TESS archive light curve included? | Yes, `providers/tess/`, id `tess` |
| Are TESS pixel products included? | No |
| Where do tests go? | `tests/` |
