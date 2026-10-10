---
name: lc-discovery-provider
description: >-
  Add or change an lc_discovery mission plugin (search_catalog, fetch_lightcurve,
  enrich). Use when registering a mission, editing providers/, TAP/ADQL, photcal,
  or a file under docs/providers/.
---

# lc_discovery mission plugins

Read `docs/adding_a_lightcurve_provider.md` and `docs/schema.md`. Architecture detail: `docs/mission_lightcurve_providers.md`. Per-mission rules: `docs/providers/<mission_id>.md`.

## Boundary

Plugins live under `src/lc_discovery/providers/<mission_id>/`. They return catalogue tables and **VOTable bytes**. They do not import any application package. Enrich is the only step that may change the retrieved product. Every calibration change is written in that mission’s provider note first.

Register the class in `src/lc_discovery/registry.py`. Applications call `list_missions`, `search`,
`resolve_target`, `archive_id_from_identifiers`, and `fetch`.

## Description

Set `description` on the provider (checklist in `docs/adding_a_lightcurve_provider.md`, section 2.1). Use `TO CONFIRM` for facts not yet checked; do not guess coverage dates, bands or references. When `supports_id_lookup` is true, include the "Id lookup" line: which id the mission takes as `archive_id`, and which Simbad identifier it comes from (or that Simbad does not list it). Set `supports_discovery_time_filter` to match the description: false when the search ignores time windows.

## Search

Implement `search_catalog` with cone, name, and/or archive id according to `MissionCapabilities`. Do not invent collection names or filter identifiers. Opaque `lc_key` via package `lc_key` helpers inside the plugin only. Extra result-table columns are a declared `(field, header)` list on the provider (default none). Do not add mission-specific names to the core catalogue schema.

## Fetch

`fetch_lightcurve` returns enriched bytes. Keep every science photometry
column the archive supplied; attach PhotCal per column. Do not write VOTables
to disk for debugging.

## Tests

Add regressions under `tests/` that import `lc_discovery` only. Do not load files from `/tmp`. Mock remote calls; mark live ones `@pytest.mark.integration`.

## Local product cache

If the mission keeps a local copy of archive products, set
`supports_force_refresh=True` and `supports_cache_purge=True`, override
`purge_cached_product(lc_key)` (delete the one product, return whether a file
was deleted), and make `fetch_lightcurve(force_refresh=True)` discard that
product first. Document the cache in `docs/providers/<mission_id>.md`.

## Behaviour

Fail fast. No silent photcal defaults. Discuss before coding unless the developer ordered implementation.
