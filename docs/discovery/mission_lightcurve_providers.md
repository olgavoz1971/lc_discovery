# Multi-Mission Lightcurve Providers — Architecture Guide

**Audience:** AI coding agents and maintainers implementing a scalable, mission-agnostic lightcurve page.

**Human-readable how-to:** [adding_a_lightcurve_provider.md](adding_a_lightcurve_provider.md) — shorter checklist for plugging in a new provider (including TAP).

**Discovery schema and provider notes:** [README.md](README.md).

**Status:** Implemented for Discovery (2026-07-30). `lc_discovery/` registry, Gaia DR3 AIP/ARI/VEB, **ASAS-SN** (`lc_discovery/providers/asassn/`), search orchestration (`utils/lc_discovery_search.py`), Submit + Retrieve on `/lc_discovery`. Legacy `/asassn` page remains until retired.

**Related docs:**
- [lightcurve_data_flow.md](lightcurve_data_flow.md) — existing layer boundaries (`VOLightCurve` ↔ `CurveDash` ↔ export)
- [caching_architecture.md](caching_architecture.md) — shared archive cache vs user session cache
- [structure.md](structure.md) — repository layout

**Out of scope for this design:** TESS cutout / TPF pixel workflows (`tess_cutout.py`, `lightcurve_tess_srv.py`). Those pages search *observations* and may *build* lightcurves from pixels. This design targets missions that already expose *catalogued lightcurves* (ASAS-SN, future VO/IRSA/pyvo archives).

---

## 1. Goal

Replace per-mission Dash pages (starting from `pages/lightcurve_asassn.py`) with **one generic page** where the user:

1. Selects **one mission** at a time
2. Enters a **target** (coordinates, mission-native ID, or generic name such as `AA And`)
3. Browses a **standardised catalog table** (one row = one plottable lightcurve)
4. Fetches the selected lightcurve
5. Plots, processes (trim, select, fold, mag/flux), and exports using **existing shared UI utilities**

Search is **not cone-only**. Three distinct discovery strategies exist (§9): **cone search** (sky position), **direct archive lookup** (mission ID — no coordinates), and **Simbad-assisted** resolution (mission picks its ID from Simbad cross-identifiers before falling back to cone or main-name retry).

Mission-specific remote access (SkyPatrol, pyvo, IRSA, datalink, …) must be **reusable outside Dash** (Jupyter notebooks, CLI, other projects).

---

## 2. Core design decision: fetch returns VO, not CurveDash

### Wrong boundary (rejected)

```text
MissionProvider.fetch() → CurveDash
```

`CurveDash` is an **application working model** (selection columns, phase, `active_domain` toggle state, in-place trim/delete). Coupling missions to it makes adapters unusable elsewhere and leaks UI concerns into the data layer.

### Correct boundary (adopted)

```text
MissionProvider.fetch() → VOLightCurve   (VO-standard lightcurve)
App boundary:              volc_to_curvedash() → CurveDash
Export:                    export_curvedash() → VOTable / ECSV / CSV
```

| Layer | Module | Responsibility |
|-------|--------|----------------|
| Mission adapters | `lc_discovery/` | Remote query + normalisation to VO |
| Search orchestration | `utils/lc_discovery_search.py` *(planned)* | Parse coords vs name; Simbad once; call provider; build markdown summary |
| Simbad (shared) | `utils/` *(e.g. coord / ask_simbad)* | Generic name resolution; **does not** parse Gaia/TIC IDs |
| VO standard | `volightcurve/` | Ingest, validate, `write_vo_lightcurve` |
| App bridge | `utils/lc_bridge.py` | `volc_to_curvedash`, `export_curvedash` |
| Interactive state | `utils/curve_dash.py` | Trim, select, fold, serialisation for session cache |
| Export profiles | `utils/mission_config/` | Static PhotCal, filter IDs, profile kwargs |
| Generic UI | `pages/lightcurve_discovery.py` | One page; thin callbacks |
| Tests | `tests/` | Provider contract + VO compliance |

See [lightcurve_data_flow.md](lightcurve_data_flow.md) for the existing VO ↔ CurveDash pipeline.

---

## 3. End-to-end data flow

```text
┌──────────────────────────────────────────────────────────────────┐
│  Generic LC page (Dash)                                          │
│  mission dropdown · cone search · AgGrid · load · plot · export  │
└────────────────────────────┬─────────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│  Mission registry  —  mission_id → provider instance             │
└────────────────────────────┬─────────────────────────────────────┘
                             │
              ┌──────────────┴──────────────┐
              ▼                             ▼
   search_catalog(...)              fetch_lightcurve(lc_key)
              │                             │
              ▼                             ▼
   LightcurveCatalogTable            VOLightCurve
   (project schema)                  (VO-LC profile)
                                              │
                                              ▼
                                    volc_to_curvedash()  ← lc_bridge
                                              │
                                              ▼
                                    CurveDash → session cache
                                              │
                                              ▼
                              lc_figure · lc_interaction · export
```

---

## 4. Mission provider API (ABC / Protocol)

Location: **`lc_discovery/`** (uses the sibling ``volightcurve`` package; reusable outside Dash).

Architecturally this is **a registry of strategy/adapters implementing a shared provider interface** — often shortened to **plugin registry** or **provider registry**. Each mission file is an *adapter* (archive API → standard catalog + `VOLightCurve`); the *registry* picks which adapter runs; new missions extend the system without changing the Discovery page (open/closed principle).

Keep the base class **thin**. Shared logic belongs in helpers, not a fat inheritance tree. Use a **registry** for discovery.

### 4.1 Identity (class-level)

| Attribute | Example | Purpose |
|-----------|---------|---------|
| `mission_id` | `"asassn"` | Stable slug for registry and `lc_key` |
| `display_name` | `"ASAS-SN Sky Patrol"` | UI label |
| `export_profile` | `"asassn"` | Passed to `export_curvedash(..., profile=...)` |
| `capabilities` | flags struct | What search modes the mission supports |

Suggested capability flags:

- `supports_cone_search` — user-supplied RA/Dec + radius
- `supports_id_lookup` — direct archive query by mission-native ID (e.g. Gaia `source_id`, TIC)
- `supports_name_resolve` — mission accepts generic `object_name` without prior Simbad step
- `supports_force_refresh`
- `provides_catalog_epoch_period` (folding hints in catalog or fetch metadata)

**Important:** `supports_id_lookup` means **direct archive query by identifier** (like `WHERE source_id = …`). It does **not** mean “resolve ID to coordinates and run a cone search”.

### 4.2 Required methods

#### `search_catalog(...) -> LightcurveCatalogTable`

Primary discovery entry point. Signature accepts named parameters; the **provider** decides which arguments apply:

```python
search_catalog(
    *,
    ra_deg: float | None = None,
    dec_deg: float | None = None,
    radius_arcsec: float | None = None,
    object_name: str | None = None,
    archive_id: str | None = None,
    **mission_options,
) -> LightcurveCatalogTable
```

| Call pattern | Who initiates | Provider behaviour |
|--------------|---------------|-------------------|
| `ra_deg`, `dec_deg`, `radius_arcsec` | Generic orchestrator (coords parsed from Target) | Cone search when `supports_cone_search` |
| `object_name` | Generic orchestrator (Target is not coordinates) | **Mission file** parses name/ID (`Gaia DR3 123…`, TIC, ASAS-SN name, …) and queries archive **without** converting IDs to cone search |
| `archive_id` (+ optional `object_name` for display) | Generic orchestrator after Simbad + `pick_archive_id_from_simbad` | Direct ID lookup — **no coordinates** |

The generic layer **must not** parse `Gaia DR3 …`, `TIC …`, or other mission-specific formats. That logic lives only in `lc_discovery/<mission>.py` (and future TESS/Kepler adapters the same way).

**ASAS-SN note:** No true cone search — lookup is by source name or Gaia ID. Returns a **degenerate catalog** (0–2 rows, one per filter band).

**Gaia note:** User may enter decimal coordinates (cone) **or** a Gaia `source_id` / `Gaia DR3 …` string (direct lookup inside the relevant registered `lc_discovery/providers/gaia_dr3_*` package).

#### `fetch_lightcurve(lc_key: str, *, force_refresh: bool = False) -> VOLightCurve`

Returns an in-memory **`VOLightCurve`** compliant with the **skvo_veb VO-LC profile** (see §7). Called on **row select / Load**, not on Submit.

Optional internal result type for caching:

```python
@dataclass
class MissionFetchResult:
    volc: VOLightCurve
    votable_bytes: bytes | None = None  # for shared disk cache
```

Public API can expose `.volc` as the primary handle; bytes are produced for cache layers.

### 4.3 Simbad cross-match (mission-specific ID pick)

When the user enters a **generic name** (e.g. `AA And`) and wants Gaia data, Simbad often returns cross-identifiers including mission-native IDs. The **mission provider** must pick its own ID from the Simbad result — the generic layer does not know Gaia vs TIC formats.

```python
@dataclass
class MissionArchiveMatch:
    archive_id: str       # mission-native id for archive query (e.g. Gaia source_id string)
    match_kind: str       # e.g. "gaia_source_id", "tic", "kepler_id"
    matched_label: str    # human-readable label for markdown UI (e.g. "Gaia DR3 1791119426789765632")
```

```python
def pick_archive_id_from_simbad(self, simbad_result) -> MissionArchiveMatch | None:
    """Return this mission's archive ID from Simbad identifiers, or None."""
```

Examples (each implemented only in the mission file):

| Mission | Simbad scan | Returns |
|---------|-------------|---------|
| Gaia | `Gaia DR3 …` / numeric source id | `MissionArchiveMatch(..., match_kind="gaia_source_id", ...)` |
| TESS *(future)* | `TIC …` | `match_kind="tic"` |
| Kepler *(future)* | KIC/KP identifiers | `match_kind="kepler_id"` |
| ASAS-SN *(future)* | Gaia id or ASAS-SN-specific ids | mission-defined |

If this returns a match, orchestrator calls `search_catalog(archive_id=…)` (direct lookup). **Do not** convert the ID to RA/Dec for cone search unless the direct lookup returns empty and cone fallback is the agreed last resort (§9).

### 4.4 Strongly recommended helpers

| Method | Purpose |
|--------|---------|
| `validate_lc_key(lc_key: str) -> bool` | Safe round-trip through `dcc.Store` |
| `cache_key(lc_key: str) -> str` | Normalised key for `flask_caching` / disk cache |

Shared Retrieve caching for Discovery is **not wired** yet. See
[TODO.md](TODO.md) ticket 1.
| `default_search_radius_arcsec() -> float` | Mission-specific default cone radius |

### 4.5 What providers must NOT do

- Return `CurveDash`
- Build Plotly figures
- Import Dash
- Implement trim, fold, or export logic (use shared utils)
- Encode export XML inline (use `mission_config` + `write_vo_lightcurve`)

The **generic orchestrator** must not parse mission-specific ID formats (Gaia DR3, TIC, …); it only detects coordinates via `utils/coord` (§9).

---

## 5. Standardised catalog table (search results)

**One row = one plottable lightcurve** (not one row per source). Example: ASAS-SN same target in `V` and `g` → two rows.

Implement as Astropy `Table` or pandas DataFrame with **enforced column names**. Provide helpers in `lc_discovery/catalog_schema.py`:

- `empty_catalog_table()`
- `validate_catalog_table(t)`
- `catalog_row_to_aggrid_dict(row)`

### 5.1 Required columns

| Column | Type | Description |
|--------|------|-------------|
| `distance_arcsec` | float | Separation from search centre |
| `ra_deg` | float | ICRS right ascension (degrees) |
| `dec_deg` | float | ICRS declination (degrees) |
| `object_name` | str | Mission/database label |
| `filter_name` | str | Human-readable filter (e.g. `"ASAS-SN g"`) |
| `lc_key` | str | Opaque fetch handle (see §5.3) |

### 5.2 Optional columns (present, nullable)

| Column | Type | Description |
|--------|------|-------------|
| `filter_identifier` | str | FPS / IVOA filter ID |
| `n_points` | int | Epoch count preview |
| `time_start_mjd` | float | Coverage start |
| `time_end_mjd` | float | Coverage end |
| `mag` | float | Catalogue magnitude if available |
| `survey` | str | Sub-survey or programme |
| `provider_note` | str | Tooltip / extra context |
| `epoch` | float | Catalogue folding epoch (full JD) |
| `period` | float | Catalogue period (days) |

Use `resolve_catalog_epoch()` from `lc_config.py` when storing epochs — never use `0` or `-2400000.5` as missing-value sentinels.

---

## 6. VO-LC profile (fetch output standard)

Mission fetch results must conform to the **skvo_veb VO Lightcurve Profile**, owned by `volightcurve/` and evolved there without breaking mission adapters.

This is **not** “any VOTable from the internet” — it is the format produced by `write_vo_lightcurve()` and parsed by `VOLightCurve`.

### 6.1 Minimum invariants

**Table columns**
- `obs_time` — UCD `time.epoch`; MJD or JD per `TIMESYS/@timeorigin`
- `phot` — flux or magnitude with correct phot UCD
- `flux_error` (optional) — `stat.error;phot.*`
- `label` (optional) — e.g. sector ID, UCD `meta.id;meta.dataset`

**TIMESYS**
- `timescale`, reference position, `timeorigin` explicit (typically `2400000.5` when `obs_time` is MJD)

**PhotCal GROUP** (when mission supplies calibration)
- `filterIdentifier` (FPS-style)
- `zeroPointFlux` / `zeroPointReferenceMagnitude` when applicable
- `effectiveWavelength` when known

**Table PARAMs** (when available)
- `ra`, `dec`, `period`, `epoch`, `filter`, pipeline/authors metadata

Mission providers assemble these via **`mission_config.*`** helpers and **`write_vo_lightcurve()`** — they do not invent column names.

### 6.2 Validation strategy

Before returning from `fetch_lightcurve()`:

1. Build compliant VOTable (via `write_vo_lightcurve` + mission profile kwargs)
2. Parse into `VOLightCurve` as a self-check
3. *(Future)* call `VOLightCurve.validate_compliance()`

Tests in `tests/volightcurve/` and mission-specific export tests are the regression harness.

### 6.3 Planned volightcurve enhancements

Not implemented yet; agents should prefer these over ad-hoc mission logic:

| Enhancement | Purpose |
|-------------|---------|
| `VOLightCurve.from_table(table, timesys=..., photdms=...)` | Build without file round-trip |
| `validate_compliance()` | Enforce VO-LC profile |
| `to_votable_bytes()` | Symmetric serialisation |
| Profile version in `creator` metadata | e.g. `skvo_veb/VO-LC/1` for schema evolution |

---

## 7. `lc_key` format

Opaque handle stored in catalog rows and `dcc.Store`. Must be JSON-serialisable and small.

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
- Always include `mission_id` and schema version `v`
- `payload` is mission-private (IDs, band codes, datalink tokens)
- Use stable JSON key ordering for cache hashing
- Never include secrets or credentials
- For datalink missions, prefer structured tokens over raw URLs in the grid (URL may live inside `payload`)

Only the owning provider parses `payload`.

---

## 8. Registry

The **provider registry** (`registry.py`) maps `mission_id` → provider instance. It is the single discovery point for the UI and for notebooks/CLI callers.

```python
# lc_discovery/registry.py

PROVIDERS: dict[str, MissionLightcurveProvider]

def get_provider(mission_id: str) -> MissionLightcurveProvider: ...
def list_missions() -> list[MissionDescriptor]: ...
```

Adding a mission:
1. Implement provider in `lc_discovery/<mission>.py`
2. Add/export profile in `utils/mission_config/<mission>.py` if not present
3. Register in `registry.py`
4. Add tests under `tests/` (catalog schema, `lc_key` round-trip, fetch → VO compliance)
5. **No changes** to generic page callbacks if the contract holds

---

## 9. Search orchestration (agreed design)

Location: **`utils/lc_discovery_search.py`** — pure Python, no Dash imports.

The Discovery **Submit** callback calls a single entry point:

```python
run_catalog_search(
    provider: MissionLightcurveProvider,
    target: str,
    radius_value: float,
    radius_unit: str,  # arcsec | arcmin | deg → converted to arcsec once
) -> SearchOutcome
```

```python
@dataclass
class SearchOutcome:
    catalog: Table
    resolved_markdown: str       # free markdown for the object card (§10)
    search_mode: str             # see flow below
    centre_ra_deg: float | None  # for display only; do not write back to Target input
    centre_dec_deg: float | None
    user_target: str             # echo of raw Target field
    archive_match: MissionArchiveMatch | None  # when Simbad + pick_archive_id_from_simbad succeeded
```

### 9.1 Three catalog discovery strategies

| Strategy | Trigger | Action | Coordinates used? |
|----------|---------|--------|-------------------|
| **A. Cone** | Target parses as ICRS coordinates (`utils/coord.parse_coord_to_skycoord`) | `search_catalog(ra_deg, dec_deg, radius_arcsec)` | User-supplied |
| **B. Direct** | Target is not coordinates; provider recognises mission ID/name | `search_catalog(object_name=target)` or `search_catalog(archive_id=…)` inside mission file | **No** for ID lookup |
| **C. Simbad-assisted** | B returned empty; generic Simbad resolve | See §9.2 | Only if cone fallback (last resort) |

**Submit returns catalog rows only.** `fetch_lightcurve(lc_key)` runs later on row select / Load.

### 9.2 Flow for non-coordinate Target (e.g. `AA And`, `Gaia DR3 123…`)

```text
Submit(target, mission, radius)
  │
  ├─ parse_coord_to_skycoord(target)?  [generic: utils/coord]
  │     yes → strategy A (cone) → STOP
  │
  └─ no
        │
        ├─ 1) provider.search_catalog(object_name=target)
        │      non-empty? → STOP (strategy B; mission parsed ID/name internally)
        │
        ├─ 2) simbad_resolve(target)   [shared utils; one query]
        │      fail → user-visible error
        │
        ├─ 3) match = provider.pick_archive_id_from_simbad(simbad_result)
        │      match? → search_catalog(archive_id=match.archive_id)  ← strategy C, direct ID
        │               non-empty? → STOP (markdown cites match.matched_label)
        │
        ├─ 4) elif provider.supports_cone_search:
        │      cone at Simbad RA/Dec (strategy C fallback — sky neighbourhood)
        │
        └─ 5) else:  # e.g. ASAS-SN, no cone
               retry search_catalog(object_name=simbad_main_name)
               (main/base Simbad identifier)
```

**Priority:** for a concrete object such as `AA And` + Gaia, prefer **Simbad → Gaia DR3 id → direct lookup** over **Simbad → RA/Dec → cone**. Cone is a last resort when no mission ID appears in Simbad.

**Examples:**

| User input | Mission | Expected path |
|------------|---------|---------------|
| `313.525 37.021` | Gaia | A: cone |
| `Gaia DR3 1791119426789765632` | Gaia | B: `gaia_debug` / `gaia_dr3_veb` parses source_id → direct lookup |
| `AA And` | Gaia | 1 fail → Simbad → `pick_archive_id_from_simbad` → Gaia id → direct lookup; else cone |
| `V* DP Peg` | ASAS-SN *(future)* | B or 1 → Simbad → retry with Simbad main name |

### 9.3 Markdown card and explicit fallbacks

- Show the resolved-target card only after a successful search attempt (empty catalog still shows card explaining “no rows”).
- **Do not** overwrite the Target input with coordinates; optional **corrected / canonical name** appears in markdown only (e.g. Simbad main id or `matched_label`).
- When step 1 fails and Simbad path runs, markdown must state what happened (no silent fallback — project rule).

Example:

```markdown
**AA And** — no direct Gaia match.

Resolved via SIMBAD; using **Gaia DR3 1791119426789765632** for catalogue search.
```

### 9.4 What the generic layer must NOT do

- Parse `Gaia DR3 …`, `TIC …`, Gaia numeric ids, KIC, etc.
- Turn archive IDs into coordinates for cone search when direct lookup is the correct semantics
- Import Dash or build Plotly figures

---

## 10. Discovery page (UI)

**Implemented (UI shell):** `pages/lightcurve_discovery.py` — navbar **Lightcurve Discovery**, path `/lc_discovery`.

Reuse patterns from `pages/lightcurve_asassn.py` and `lightcurve_tess_srv.py`:
- `lc_session_cache` for server-side `CurveDash` storage
- `lc_figure`, `lc_interaction` for plot/trim/select
- `lc_bridge.export_curvedash` for download
- MJD/Date axis, mag/flux toggle, phase folding

### 10.1 Page stores (lightweight)

| Store | Content |
|-------|---------|
| `store_lc_discovery_catalog` | Serialised catalog row dicts (not full LC arrays) |
| `store_lc_discovery_selected_key` | Selected row's `lc_key` |
| `store_lc_discovery_resolved_target` | Search outcome metadata + markdown source |
| `store_lc_discovery_user_tab_id` | Session cache UUID (existing pattern) |
| `store_lc_discovery_selected_perm` | Client list of marked `perm_index` values (not the lightcurve) |
| `store_lc_discovery_zoom` | Client axis snapshot for restore after delete |

### 10.2 Callback responsibilities

| Callback | Action |
|----------|--------|
| **Mission change** | Clear catalog, hide object card, clear LC session state; **keep Target field text** |
| **Submit query** | Background job: `run_catalog_search()` → AgGrid + markdown card |
| **Cancel query** | Cancel background search (same pattern as TESS srv) |
| **Load / row select** | `provider.fetch_lightcurve(lc_key)` → `volc_to_curvedash` → session cache |
| **Restore (in-tab)** | `restore_lc_discovery_tabs`: cache hit → enable Light curve tab and select it. `restore_lc_discovery_search_table`: rebuild AgGrid / object card from session stores. `refresh_lc_discovery_aladin`: remount the sky map from the same stores (not from AgGrid). Plot from persisted revision. Do not require catalogue `rowData` to admit a working curve. Table and Aladin highlight callbacks stay separate so restoring the grid does not require `lc_discovery_aladin` to already exist. |
| **Plot mark / Unselect / Delete** | Client union of `perm_index`; Unselect clears the perm store; Delete mutates the session-cached `CurveDash` |
| **Replot / trim / export** | Unchanged shared utils on `CurveDash` |

### 10.3 Background callbacks

Configured **once** in `app.py` via `Config.get_background_callback_manager()`:

| Environment | Manager |
|-------------|---------|
| Production (`USE_REDIS=true`) | **CeleryManager** (Redis broker/backend) |
| Local dev | **DiskcacheManager** (`DISKCACHE_DIR`) |

Discovery Submit uses `background=True`, `running=[disable Submit, enable Cancel]`, `cancel=[Cancel button]` — same as `lightcurve_tess_srv.py`. **Do not** add a page-local callback manager; the app-level manager is sufficient.

Do **not** duplicate ASAS-SN callback logic inline — call `run_catalog_search()` from the Submit callback.

---

## 11. Caching

Two distinct cache tiers (see [caching_architecture.md](caching_architecture.md)):

| Cache | Key | Stored value |
|-------|-----|--------------|
| **Search** | `(mission_id, search_mode, normalised_target_or_coords, radius_arcsec)` | Serialised catalog table |
| **Fetch** | `(mission_id, lc_key_hash)` | **VOTable bytes** (canonical) |
| **User session** | `{user_tab_id}_data` | Serialised `CurveDash` (after bridge) |

Mission-internal caches (e.g. ASAS-SN pickle in `ASASSN_CACHE_DIR`) remain **private** inside the provider, before VO normalisation.

Fetch cache should store VOTable bytes so multiple users and notebooks share the same archive product.

---

## 12. Relationship to existing modules

| Existing module | Role in new architecture |
|-----------------|--------------------------|
| `pages/lightcurve_asassn.py` | Reference UI; to be superseded by generic page |
| `utils/request_asassn.py` | Becomes internals of `lc_discovery/providers/asassn.py`; output refactored to `VOLightCurve` |
| `utils/mission_config/asassn.py` | PhotCal + export profile; used when **building** fetch output |
| `utils/lc_bridge.py` | `volc_to_curvedash` at app boundary; export unchanged |
| `volightcurve/` | Source of truth for VO-LC profile |
| `utils/coord.py`, `utils/ask_simbad.py` | Coordinate parsing + Simbad for orchestrator (§9) |
| `utils/lc_discovery_search.py` *(planned)* | Search orchestration (§9) |
| `utils/lc_figure.py`, `lc_interaction.py`, `lc_session_cache.py` | Shared by Discovery page |

---

## 13. Provider product notes

Per-mission discovery, retrieval, and any calibration this code adds:

- [Index](README.md)

After each fetch, an error column with no photcal of its own is linked to
the photcal of the single matching magnitude or flux column
(``share_photcal_with_unlinked_errors``). An error column the archive
already linked is not changed. Several calibrated parents are left alone.

## 14. ASAS-SN adapter (implemented)

Package: `lc_discovery/providers/asassn/` (`AsassnProvider`, registered as `asassn`).

| Area | Behaviour |
|------|-----------|
| Discovery | `stellar_main` + `cols` (`asas_sn_id`, `ra_deg`, `dec_deg`, `pstarrs_g_mag`); cone, Gaia id, or Simbad name; **two candidate rows** per source (`g`, `V`); `mag` on **g** only; shared `provider_note`; no discovery time filter |
| Truncation | Cap **source count** (100) before ×2; entity label “ASAS-SN sources” |
| Fetch | `lc_key`: `asas_sn_id` + `band`; Sky Patrol `download=True`; empty band → fail fast; epoch/period via `aavsovsx` ADQL at enrich |
| Cache | None in provider (legacy page still uses `request_asassn` pickle cache) |
| Export | `export_profile="asassn"` → `mission_config.asassn` via `export_curvedash` |
| Legacy | `/asassn` + `utils/request_asassn.py` unchanged |

Tests: `tests/test_lc_providers_asassn.py` (mocked Sky Patrol); `tests/test_asassn_export.py` (legacy export profile).

---

## 15. Implementation order (for agents)

**Done:**
1. `lc_discovery/catalog_schema.py`, `lc_key.py`, `base.py` (`MissionArchiveMatch`), `registry.py`
3. Gaia DR3 AIP, ARI, VEB TAP providers
4. **`lc_discovery/providers/asassn/`** — Sky Patrol discovery + fetch → `VOLightCurve`
5. `utils/simbad_resolver.py`, `utils/lc_discovery_search.py` (Discovery orchestration)
6. Discovery UI + Submit/Retrieve + truncation notices
7. Tests: `test_lc_providers_*`, `test_lc_discovery_search.py`, `test_lc_providers_asassn.py`

**Next:**
- Retire standalone `/asassn` when Discovery parity is confirmed
- Search result caching (§11) — optional follow-up

---

## 16. Error handling

- User-visible errors: `PipeException` (existing pattern)
- Providers wrap remote failures with mission context: `"ASAS-SN: source not in Sky Patrol"`
- Empty catalog after a successful search → empty AgGrid + informative markdown, **not** an exception
- Simbad / parse failures → user-visible alert
- Fallback paths (Simbad after failed direct name search) must be **documented in markdown** on the object card — no silent fallback (project rule)

---

## 17. Resolved design decisions

| Topic | Decision |
|-------|----------|
| Discovery route | `/lc_discovery` (separate from `/asassn`) |
| Target field on mission change | **Keep** user text; clear catalog + hide card |
| Target field after Simbad | **Do not** write coordinates back; canonical name in markdown only |
| Simbad for non-cone missions | Retry `search_catalog(object_name=simbad_main_name)` |
| Simbad for cone missions | `pick_archive_id_from_simbad` → direct ID first; cone at Simbad coords last |
| Background callbacks | App-level Celery (prod) or Diskcache (dev); `background=True` on Submit |
| Catalog persistence | Store serialised row dicts in `store_lc_discovery_catalog` after search; `restore_lc_discovery_search_table` writes them back to AgGrid on in-tab remount |

**Still open:** cone/radius UX for name-only missions (show radius disabled with hint vs hide).

---

## 18. Summary for agents

| Question | Answer |
|----------|--------|
| What is this architecture called? | **Plugin registry** / **provider registry** (§4) |
| Where do missions live? | `lc_discovery/` |
| Where is search logic orchestrated? | `utils/lc_discovery_search.py` (§9) |
| Three search strategies? | Cone (coords), direct (mission ID/name in provider), Simbad-assisted (§9.1) |
| Gaia ID lookup | Direct archive query in the provider — **not** ID → coords → cone |
| Simbad + `AA And` + Gaia | `pick_archive_id_from_simbad` → `MissionArchiveMatch` → direct lookup |
| What does search return? | Standard catalog table (§5) |
| What does fetch return? | **`VOLightCurve`**, not `CurveDash` |
| Where does CurveDash appear? | After `volc_to_curvedash()` in the Dash page only |
| Where is the VO standard defined? | `volightcurve/` + `write_vo_lightcurve` |
| Where is export config? | `utils/mission_config/` |
| Is TESS cutout/srv included? | No — separate pixel/archive pages |
| Tests go where? | `skvo_veb/tests/` |
