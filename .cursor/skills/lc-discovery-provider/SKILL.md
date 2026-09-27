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

Plugins live under `src/lc_discovery/providers/<mission_id>/`. They return catalogue tables and **VOTable bytes**. They do not import Dash, `CurveDash`, or `volightcurve`. Enrich is the only step that may change the retrieved product. Every calibration change is written in that mission’s provider note first.

Register the class in `src/lc_discovery/registry.py`. Applications still call `search` / `fetch`, not the class.

## Search

Implement `search_catalog` with cone, name, and/or archive id according to `MissionCapabilities`. Do not invent collection names or filter identifiers. Opaque `lc_key` via package `lc_key` helpers inside the plugin only.

## Fetch

`fetch_lightcurve` returns enriched bytes. Do not copy a per-plugin `_save_debug_votable`. A shared debug write belongs on `api.fetch` when that phase is implemented.

## Tests

Add regressions under `tests/` that import `lc_discovery` only. Do not load files from `/tmp` or the Dash app tree.

## Behaviour

Fail fast. No silent photcal defaults. Discuss before coding unless the developer ordered implementation.
