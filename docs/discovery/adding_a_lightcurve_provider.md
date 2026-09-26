# Adding a Lightcurve Provider

**Audience:** Developers who want to connect a new archive or survey to **Lightcurve Discovery** (`/lc_discovery`). You do not need to know Dash or the plot UI — only how your archive exposes catalogue rows and lightcurve files.

**Technical reference:** [mission_lightcurve_providers.md](mission_lightcurve_providers.md) (full architecture, search flows, caching).

---

## What you are building

A **provider** is a small adapter between an external archive and the Discovery page.

It does two jobs:

1. **Search** — given a target (coordinates, name, or archive id), return a **catalogue table**: one row per plottable lightcurve (filter, band, sector, etc.).
2. **Fetch** — given one row’s opaque **`lc_key`**, download or build a **VO-standard lightcurve** (`VOLightCurve`) for plotting and export.

The Discovery page, plot tools, and export logic stay unchanged. You register the provider once; the UI picks it up from the mission dropdown.

```text
User on /lc_discovery
        │
        ▼
  registry.get_provider(mission_id)
        │
        ├── search_catalog(...)  ──►  standard catalogue table
        │
        └── fetch_lightcurve(lc_key)  ──►  VOLightCurve  ──►  plot / export
```

---

## Before you start

Gather this information from the archive documentation or a TAP service description:

| Question | Example (Gaia DR3 VEB) |
|----------|-------------------------|
| What is the stable **mission id** slug? | `gaia_dr3_veb` |
| What **display name** should users see? | `Gaia DR3 VEB` |
| How do users **find products**? | TAP table `gaiadr3_eb.ts_ssa` (cone or `source_id`) |
| How do you **open one lightcurve**? | HTTP GET on SSA column `accref` |
| Does Simbad expose your archive id? | Gaia DR3 `source_id` in cross-identifiers |
| Cone search supported? | Yes (on `ssa_location`) |
| Direct id lookup supported? | Yes (`source_id`) |

**Naming rule:** one provider = one archive/product line. Do not mix “debug mock”, “DR3 VEB”, and future “DR4 ESA” in one folder — use separate packages (see `lc_discovery/providers/gaia_dr3_veb/`).

---

## Obligatory pieces (every provider)

### 1. One package folder under `lc_discovery/`

Use a **specific** name, not a vague mission umbrella:

```text
lc_discovery/my_survey_dr1/
├── __init__.py      # exports YourProvider class
└── provider.py      # the adapter class (minimum)
```

Extra files (`config.py`, mappers, fetch helpers) are **your choice** — they keep `provider.py` readable but are not required by the framework.

### 2. The provider class (`provider.py`)

Subclass `MissionLightcurveProvider` from `lc_discovery/base.py`.

**Class attributes (required):**

| Attribute | Purpose |
|-----------|---------|
| `mission_id` | Short slug, e.g. `"my_survey_dr1"` — used in registry and inside every `lc_key` |
| `display_name` | Label in the mission dropdown |
| `export_profile` | Usually same as `mission_id` for Discovery (legacy pages may use `mission_config` profiles) |
| `capabilities` | Flags: cone search, id lookup, force refresh, etc. |
| `is_mock` | Optional metadata (`True` for synthetic catalogues); does **not** hide a registered provider |

**Methods you must implement:**

| Method | Purpose |
|--------|---------|
| `search_catalog(...)` | Return an Astropy `Table` matching the [shared catalogue schema](mission_lightcurve_providers.md#5-standardised-catalog-table-search-results) |
| `fetch_lightcurve(lc_key, ...)` | Decode `lc_key`, retrieve data, return `VOLightCurve` |

**Methods strongly recommended for Discovery:**

| Method | When needed |
|--------|-------------|
| `pick_archive_id_from_simbad(simbad_result)` | User types a common name (`AA And`) and Simbad lists your archive id |
| `default_search_radius_arcsec()` | Cone search default (base class returns `10.0` if omitted) |

Everything else (`validate_lc_key`, `descriptor`, `_require_cone_search`) is inherited from the base class.

### 3. Catalogue rows and `lc_key`

Each search result row **must** include at least:

`distance_arcsec`, `ra_deg`, `dec_deg`, `object_name`, `filter_name`, `lc_key`

Optional standard columns include `t_min`, `t_max`, `n_points`, `period`, and others listed in
`catalog_schema.py`. Populate time coverage when the archive provides it cheaply at search time.
Set `MissionCapabilities.supports_discovery_time_filter=False` when discovery cannot honour the
UI earliest/latest time fields (Gaia DR3 AIP fetches epoch photometry only on row load). The
Discovery results table hides ``t_min`` / ``t_max`` when this flag is false.

Set `discovery_catalog_includes_object_class=True` when the discovery query returns a
classification or object type column (SSA ``dataproduct_type``, Gaia variability class, etc.).

Set `discovery_catalog_includes_n_points=True` when the discovery catalogue includes per-row
epoch counts (``ssa_length``, ``nobsrel``, detection counts, etc.).

Use helpers from `lc_discovery/catalog_schema.py`:

- `empty_catalog_table()` — no matches
- `validate_catalog_table(table)` — before returning

Each `lc_key` is a small JSON string:

```json
{"mission_id":"my_survey_dr1","v":1,"payload":{"your":"fetch","fields":"here"}}
```

Build it with `encode_lc_key(mission_id, payload)`. Only your provider reads `payload` in `fetch_lightcurve`.

### 4. Register in `lc_discovery/registry.py`

Registration is the **only** switch that exposes a provider on Lightcurve Discovery.
There is no separate “enabled” flag or page-level filter.

```python
from skvo_veb.lc_providers.my_survey_dr1 import MySurveyDr1Provider

PROVIDERS = {
    ...
    MySurveyDr1Provider.mission_id: MySurveyDr1Provider(),
}
```

After this, the new mission appears in the Discovery dropdown automatically.

### 4.1 Unregistering a provider

To remove a mission from the Discovery UI (and from `get_provider` / `list_missions`):

1. Delete its import and entry from `PROVIDERS` in `lc_discovery/registry.py`.
2. Update tests that assert the mission appears in `list_missions()` or call
   `get_provider("<mission_id>")`.
3. Update docs that list the mission as a live Discovery option.

**What to do with the provider package:**

| Situation | Action |
|-----------|--------|
| Development / test-only provider (e.g. synthetic catalogue, VOLightCurve format experiments) | **Keep** `lc_discovery/<provider>/`. Tests import the class directly (`GaiaDr3Provider()`), not via the registry. |
| Retired production provider, code still useful as reference | Move to `lc_discovery/obsolete/<provider>/` (must not be imported by production code). |
| Retired provider, no remaining imports | Delete `lc_discovery/<provider>/`. |

The debug mock `gaia_debug` has been removed.

If a mission is not in `PROVIDERS`, it is unavailable to Discovery and
`get_provider(mission_id)` raises `PipeException`.

### 5. Tests under `skvo_veb/tests/`

Minimum useful tests:

- Catalogue mapping produces valid columns and `lc_key` round-trip
- `search_catalog` with mocked remote calls returns expected row count
- `fetch_lightcurve` with mocked download returns a `VOLightCurve`

Copy patterns from `test_lc_providers_gaia_veb.py` or `test_lc_providers_gaia.py`.

---

## What you do **not** need to change

| Area | Why |
|------|-----|
| `pages/lightcurve_discovery.py` | Generic UI; talks to providers via registry |
| `utils/lc_discovery_search.py` | Orchestration only — unless you add a **new** search mode |
| Plot / trim / fold / export utils | Shared; work on `CurveDash` after fetch |
| `utils/mission_config/` | Only for **static export profiles** on legacy pages; Discovery export uses metadata from the fetched VOTable |

Discuss with maintainers before changing shared orchestration or the base provider contract.

---

## Step-by-step checklist (any provider)

1. Create `lc_discovery/<your_provider>/` with `provider.py` and `__init__.py`.
2. Set `mission_id`, `display_name`, `capabilities`, `is_mock`.
3. Implement `search_catalog`:
   - Accept `ra_deg` / `dec_deg` / `radius_arcsec` for cone mode when supported.
   - Accept `object_name` or `archive_id` for direct lookup when supported.
   - Return `validate_catalog_table(...)` or `empty_catalog_table()`.
4. Implement `fetch_lightcurve`:
   - Validate `lc_key` (use inherited `validate_lc_key`).
   - Decode payload, call archive, return `VOLightCurve`.
   - **Enrich metadata in provider-specific code** (see [Lightcurve metadata](#lightcurve-metadata) below).
5. Optionally implement `pick_archive_id_from_simbad`.
6. Register in `registry.py`.
7. Add tests; run `pytest skvo_veb/tests/test_lc_providers_*.py`.
8. Manual smoke test on `/lc_discovery`: search → select row → Retrieve.

---

## Lightcurve metadata

Discovery export is **mission-blind**: it rebuilds a VOTable from `CurveDash.metadata['vo_envelope']` and `photcal`, not from a legacy `mission_config` profile. Providers are responsible for filling metadata on the fetched `VOLightCurve` before it enters the shared bridge.

### Obligatory (provider must supply)

| Field | Source (typical) | Stored as |
|-------|------------------|-----------|
| **Table description** | VOTable `TABLE/DESCRIPTION` | `vo_envelope.table_description` |
| **Lightcurve title** | VOTable `TABLE/@name`, corrected by provider if needed | `vo_envelope.lightcurve_title` (also `CurveDash.title` for plot captions) |

Export fails with a clear error if `table_description` is missing after ingest.

### Optional but recommended

| Field | Source (typical) | Stored as |
|-------|------------------|-----------|
| **Publication bibcode** | VOTable `PARAM name="bibcode"` | `vo_envelope.publication_id` → exported as `bibcode` PARAM |

Other envelope fields (TIMESYS, COOSYS, creator) are captured automatically by the generic bridge when present on the archive product.

### Layer separation

```text
Provider fetch (e.g. gaia_dr3_veb/fetch_metadata.py)
  → enrich VOLightCurve.table.meta (title, description, optional bibcode)
Bridge ingest (utils/lc_bridge.py)
  → _extract_vo_envelope_meta → metadata['vo_envelope']
  → volc_to_curvedash sets CurveDash.title from lightcurve_title
Discovery export (utils/lc_bridge.py)
  → build_votable_kwargs_from_metadata → write_vo_lightcurve
```

**Do not** put provider-specific title/description logic in `pages/` or `lc_bridge.py`. Gaia DR3 VEB example: archive `TABLE/@name` omits the passband, so `enrich_fetched_volightcurve` appends `" in {filter_name} filter"` using the catalogue row’s `filter_name`.

Reference: `lc_discovery/providers/gaia_dr3_veb/fetch_metadata.py`, keys in `utils/lc_config.py` (`VO_ENVELOPE_KEY_*`).

### Folding epoch and TIMESYS

When a VOTable stores `PARAM name="epoch"` without `ref="ts"`, the generic ingest assumes it shares the same `TIMESYS/@timeorigin` as the sole observation-time column (identified by `ucd=time.epoch` via `get_time_colnames`). If several time columns reference **different** timeorigins, ingest fails with a clear error.

Internally, CurveDash always stores **absolute Julian Date** for folding. On export, both `obs_time` and `epoch` are rewritten consistently for the standard MJD `TIMESYS` (`timeorigin = 2400000.5`), preserving `JD = obs_time + timeorigin`.

Implementation: sibling package ``volightcurve.time_reference``, wired through `volc_to_curvedash` and `build_votable_kwargs_from_metadata`.

---

## TAP providers (separate section)

Many archives expose a **Table Access Protocol (TAP)** service. Discovery TAP providers follow the same provider contract; they differ in **how** search and fetch are wired.

**Reference implementation:** `lc_discovery/providers/gaia_dr3_veb/`

### How a TAP provider is usually split

| File | Role | Obligatory? |
|------|------|-------------|
| `provider.py` | Implements `search_catalog` and `fetch_lightcurve` | **Yes** |
| `config.py` | TAP URL, table name, ADQL templates, dialect | Practical necessity |
| `ssa_catalog.py` (or similar) | Maps TAP result rows → standard catalogue columns + `lc_key` | Practical necessity |
| `fetch_*.py` | Downloads the actual lightcurve (often **not** via TAP) | Depends on archive |

TAP answers “**what products exist?**”. Fetch often uses a **second step** (DataLink, `accref` URL, SIA, etc.) — that is normal.

### Shared TAP transport (do not duplicate)

Use the generic client:

```python
from skvo_veb.lc_providers.tap.client import run_tap_sync_query
from skvo_veb.lc_providers.tap.dialect import TapQueryDialect

table = run_tap_sync_query(
    tap_url,
    adql_string,
    dialect=TapQueryDialect.ADQL_2_1,  # or ADQL-2.0 — see below
)
```

**Always declare the dialect** your service supports. Check the service capabilities page (e.g. `https://…/tap/capabilities`) for supported `ADQL` versions.

| Dialect constant | TAP `LANG` value | Use when |
|------------------|------------------|----------|
| `TapQueryDialect.ADQL_2_1` | `ADQL-2.1` | Service lists ADQL 2.1 (UPJS VEB does) |
| `TapQueryDialect.ADQL_2_0` | `ADQL-2.0` | Older TAP services |
| `TapQueryDialect.ADQL` | `ADQL` | Version left to the server |

### ADQL rules (not SQL)

Write queries in **ADQL**, the IVOA astronomical query language — not PostgreSQL, not plain SQL extensions.

| Do | Do not |
|----|--------|
| `SELECT … FROM schema.table WHERE …` | PostgreSQL casts (`::`), `ST_*`, `ILIKE` |
| `1 = CONTAINS(point_column, CIRCLE(ra, dec, radius_deg))` for cone on a **point column** | Reversed `CONTAINS` arguments (circle “inside” a point) |
| `CIRCLE(ra, dec, radius_deg)` on ADQL 2.1 services | Deprecated `CIRCLE('ICRS', ra, dec, r)` coord-sys argument on 2.1 |
| Numeric literals for MJD bounds: `t_min > 56889.0` | Assumed server-specific functions unless documented in TAPRegExt |

**Cone search pattern (ADQL 2.1):** the sky position column is the **first** argument to `CONTAINS`; the search circle is the **second**:

```sql
SELECT accref, ssa_bandpass, …
FROM gaiadr3_eb.ts_ssa
WHERE 1 = CONTAINS(ssa_location, CIRCLE(346.345, 47.676, 0.00278))
```

Radius in `CIRCLE` is in **degrees** (convert arcseconds ÷ 3600).

**Direct id lookup** is usually a normal `WHERE` clause on the archive’s id column — no geometry needed.

Keep ADQL builders in `config.py` (or `adql.py`) inside **your** provider package, not in `tap/client.py`. The TAP client only executes queries; each provider owns its table names and column mapping.

### TAP provider checklist

1. **Discover the service**
   - TAP base URL
   - Table name(s) from `tables` metadata
   - Supported ADQL version(s)
   - Which columns identify filter, time range, position, and download link

2. **Add `config.py`**
   - `TAP_URL`, `TAP_QUERY_DIALECT`, table name
   - Functions `adql_catalog_by_*` that return complete query strings

3. **Add row mapper**
   - Input: raw TAP `Table`
   - Output: `validate_catalog_table(...)` with one row per plottable product
   - Encode `lc_key` payload with whatever fetch needs (e.g. `accref` URL)

4. **Implement fetch**
   - TAP row → `lc_key` → your download logic → `VOLightCurve`
   - If the VOTable already matches the skvo_veb profile, parse directly; otherwise normalise via `write_vo_lightcurve` and `mission_config` helpers

5. **Wire `provider.py`**
   - `search_catalog` → build ADQL → `run_tap_sync_query` → mapper
   - `fetch_lightcurve` → decode `lc_key` → fetch module

6. **Test ADQL strings** in unit tests (assert geometry and keywords) and run at least one live query against the TAP service during development.

7. **Register** and smoke-test on Discovery.

### Example layout (Gaia DR3 VEB)

```text
gaia_dr3_veb/
├── __init__.py
├── config.py           # TAP URL, ADQL 2.1 templates, dialect
├── provider.py         # search_catalog + fetch_lightcurve
├── ssa_catalog.py      # TAP SSA rows → catalogue schema
└── fetch_accref.py     # HTTP GET accref → VOLightCurve
```

Shared utilities used but **not** part of this package:

- `lc_discovery/tap/` — generic TAP execution + dialect enum
- `lc_discovery/shared/gaia_dr3_source_id.py` — DR3 id parsing (DR4 would get its own module)

---

## Capability flags (inform the UI)

Set honest flags on `MissionCapabilities`:

| Flag | Meaning |
|------|---------|
| `supports_cone_search` | Can search by RA, Dec, radius |
| `supports_id_lookup` | Can search by archive-native id without sky cone |
| `supports_force_refresh` | Honours `force_refresh=True` on fetch (or accepts it for API compatibility) |
| `supports_name_resolve` | Provider resolves generic names itself (rare; usually Simbad handles names) |

Discovery orchestration uses these flags to choose Simbad fallbacks (see [§9 in the architecture doc](mission_lightcurve_providers.md#9-search-orchestration-agreed-design)).

---

## Common mistakes

| Mistake | Fix |
|---------|-----|
| Putting math, ADQL, or HTTP in `pages/` | Keep all archive logic in `lc_discovery/` |
| One folder for unrelated missions (“all Gaia”) | Separate package per product line |
| Returning `CurveDash` from fetch | Return `VOLightCurve`; bridge happens in `lc_discovery_load` |
| Storing large arrays in `lc_key` | Only small fetch handles (ids, URLs, band codes) |
| Cone search via “id → Simbad → coords” when direct id works | Use direct lookup first |
| PostgreSQL in TAP queries | ADQL only; verify against [ADQL 2.0 / 2.1](https://www.ivoa.net/documents/ADQL/) |
| Forgetting registry entry | Provider code exists but never appears in dropdown |
| Leaving a removed provider in `PROVIDERS` | Delete the registry entry when retiring a mission from Discovery |
| Skipping `validate_catalog_table` | AgGrid and downstream code expect fixed column names |

---

## Getting help

- **Architecture and search flows:** [mission_lightcurve_providers.md](mission_lightcurve_providers.md)
- **Repository layout:** [structure.md](structure.md)
- **Working TAP example:** `lc_discovery/providers/gaia_dr3_veb/`
- **Non-TAP / Sky Patrol example:** `lc_discovery/providers/asassn/` (cone + `query_list` on `stellar_main`, candidate band rows)

When adding a provider that needs a new search strategy or changes to shared code, agree the design with maintainers first (project rule).
