# lc_discovery

Catalogue search and calibrated light-curve fetch. Install from this tree:

```bash
pip install -e .
# with tests
pip install -e ".[dev]"
```

Search for and retrieve light curves from the registered archives. The
public calls are `list_missions`, `search`, `resolve_target`,
`archive_id_from_identifiers`, and `fetch`.

## Reading order

1. This file (`README.md`): public API, search kinds, `fetch` bytes, reading points as a `Table`.
2. [docs/schema.md](docs/schema.md): issued product and enrich rules.
3. [docs/providers/](docs/providers/): one note per mission. Calibration changes live only here.
4. [docs/adding_a_lightcurve_provider.md](docs/adding_a_lightcurve_provider.md): checklist for a new plugin.
5. [docs/mission_lightcurve_providers.md](docs/mission_lightcurve_providers.md): plugin architecture inside this package. 

Applications and agents import those names from `lc_discovery`.
They do not call mission plugins, and they do not decode `lc_key`.

```python
from lc_discovery import (
    list_missions,
    search,
    resolve_target,
    archive_id_from_identifiers,
    fetch,
)
```

## Public API

### `list_missions()`

Returns the registered missions as a list, sorted by display name. Each
entry has:

| Field | Meaning |
| --- | --- |
| `mission_id` | Stable slug passed to `search` (for example `ogle_ocvs`). |
| `display_name` | Label for a mission selector. |
| `export_profile` | Name of the export profile for this mission. |
| `capabilities` | What that mission accepts. See below. |
| `is_mock` | `True` only for a synthetic mission. None of the registered missions are mocks. |

`capabilities` is a set of flags:

- `supports_cone_search`: sky position and radius are accepted.
- `supports_name_resolve`: an object name is accepted.
- `supports_id_lookup`: a mission archive id is accepted.
- `supports_force_refresh`: `fetch(..., force_refresh=True)` is meaningful for that mission.
- `provides_catalog_epoch_period`: catalogue rows can carry epoch and period.
- `supports_discovery_time_filter`: `time_start_mjd` and `time_end_mjd` are accepted. When this is false, a time window is an error.
- `discovery_catalog_includes_object_class`: rows can carry an object class.
- `discovery_catalog_includes_n_points`: rows can carry a point count.

`list_missions()` does not return a provider object. There is no public
call that hands one out.

### `resolve_target(mission_id, name)`

Maps a target string to a mission archive id. Does not query the
catalogue. Returns `None` when the mission does not recognise the name,
or a match with `archive_id`, `match_kind`, and `matched_label`. The
caller then uses `search(..., archive_id=match.archive_id)`.

Unknown `mission_id` raises `ValueError`.

### `archive_id_from_identifiers(mission_id, identifiers, ...)`

Picks a mission archive id from Simbad-style identifier strings. Pass
the cross-identifier list; optionally `query_name` and `main_id`. Do
not pass a Simbad client object. Returns the same match type as
`resolve_target`, or `None`. Then call `search(..., archive_id=...)`.

### `search(mission_id, **kwargs)`

Searches one mission catalogue. Pass only the arguments that mission's
capabilities allow. Unknown `mission_id` raises `ValueError`.

| Argument | Meaning |
| --- | --- |
| `mission_id` | Slug from `list_missions()`. |
| `ra_deg`, `dec_deg` | ICRS position in degrees. Used with `radius_arcsec`. |
| `radius_arcsec` | Cone radius in arcseconds. |
| `object_name` | Catalogue name or identifier. |
| `archive_id` | Mission-native archive id. |
| `time_start_mjd`, `time_end_mjd` | Optional MJD window. `None` means that side is unbounded. |

Returns an Astropy `Table`. Each row includes an opaque string column
`lc_key`. The table may be empty. Callers pass `lc_key` to `fetch` and
do not parse it.

The three search kinds this package maintains are **cone**, **name**,
and **archive id**. A **time window** is an extra constraint on a
mission that sets `supports_discovery_time_filter`.

### `fetch(lc_key, *, force_refresh=False)`

Retrieves one light curve.

| Argument | Meaning |
| --- | --- |
| `lc_key` | Value from a `search` row. |
| `force_refresh` | Accepted. No shared fetch cache is wired yet. |

Returns `bytes`: the calibrated VOTable document. Enrichment has already
been applied inside the mission. A bad key, an unknown mission, or a
plugin that does not return bytes raises `ValueError`.


## Why `fetch` does not return an Astropy Table or VOTableFile

An astronomer asking for “the Astropy VOTable” usually means one of two
objects: `astropy.table.Table` after `Table.read(..., format="votable")`,
or `astropy.io.votable.VOTableFile`. This package uses Astropy for
catalogue rows (`search` returns a `Table`) and for parsing VOTable
structure inside tests and plugins. The issued light curve is still
returned as **bytes**.

The product is a **VOTable document**, not a table of columns. The
document holds `TABLE` name and description, `PARAM` with `utype` and
unit, `FIELD` with `ucd`, unit, and `ref`, photometry `GROUP` with
`FIELDref` (the calibration that ties a magnitude or flux column to its
error), `TIMESYS`, and `COOSYS`. Enrichment writes those into the XML.
That is the calibrated product.

`astropy.table.Table` keeps columns and a flat `meta` dictionary. It
does not keep photometry `GROUP`s, `FIELDref`s, or `TIMESYS` links.
Returning a `Table` would drop the calibration this package exists to
issue. To load **only the points** after `fetch`, see
[Read the points as an Astropy Table](#read-the-points-as-an-astropy-table).

`astropy.io.votable.VOTableFile` can hold that document in memory. It is
Astropy’s representation of a VOTable file. `fetch` does not return it
because the contract is the file the mission just issued. Writing that
object back with `to_xml()` can change namespaces, empty units, and
identifier spelling. The bytes are the document without that rewrite.
Callers who want `VOTableFile` parse the bytes themselves:

```python
import io
from astropy.io.votable import parse

payload = fetch(catalog["lc_key"][0])
votable = parse(io.BytesIO(payload))
```

## What is not public

Mission classes, `fetch_lightcurve`, `enrich_votable`, ADQL, TAP
clients, `get_provider`, and `encode_lc_key` / `decode_lc_key` are
inside the package. The Discovery page, CurveDash, and Aladin stay in
the application. 

## Examples

Inspect what a mission accepts before choosing a search kind:

```python
from lc_discovery import (
    list_missions,
    search,
    resolve_target,
    archive_id_from_identifiers,
    fetch,
)

for mission in list_missions():
    caps = mission.capabilities
    print(
        mission.mission_id,
        "cone=", caps.supports_cone_search,
        "name=", caps.supports_name_resolve,
        "id=", caps.supports_id_lookup,
        "time=", caps.supports_discovery_time_filter,
    )
```

### Cone search

Sky position and a radius. Requires `supports_cone_search`.

```python
catalog = search(
    "gaia_dr3_veb",
    ra_deg=346.3451680066482,
    dec_deg=47.676291847527416,
    radius_arcsec=10.0,
)
```

### Name search

An object name or catalogue identifier. Requires
`supports_name_resolve`. Missions that set this false (Pan-STARRS1 DR2,
ZTF) do not take a Simbad-style name here.

```python
catalog = search("ogle_ocvs", object_name="OGLE-LMC-RRLYR-13820")
```

If that table is empty, resolve a native spelling then search by archive
id:

```python
match = resolve_target("ogle_ocvs", "OGLE SMC-ECL- 5425")
if match is not None:
    catalog = search("ogle_ocvs", archive_id=match.archive_id)
```

After Simbad, pass identifier strings (not a Simbad object):

```python
match = archive_id_from_identifiers(
    "ogle_ocvs",
    ["OGLE SMC-ECL- 5425", "TYC 1-2-1"],
    query_name="OGLE SMC-ECL- 5425",
    main_id="V* DP Peg",
)
```

### Archive-id search

The mission-native identifier. Requires `supports_id_lookup`. The
string is that archive’s id, not a decoded `lc_key`.

```python
catalog = search("gaia_dr3_veb", archive_id="1936512041221649536")
catalog = search("ogle_ocvs", archive_id="OGLE-LMC-RRLYR-13820")
catalog = search("panstarrs1_dr2", archive_id="165243463579570976")
```

ZTF uses `archive_id` as the object id from a previous cone row of
`ztf_dr24`. Do not invent an oid.

### Time window

Optional MJD limits on missions with `supports_discovery_time_filter`.
`None` on one side means that side is unbounded. Gaia AIP, Gaia ARI,
ASAS-SN, Pan-STARRS1, and ZTF reject a time window.

```python
catalog = search(
    "ogle_ocvs",
    object_name="OGLE-LMC-RRLYR-13820",
    time_start_mjd=55000.0,
    time_end_mjd=58000.0,
)
```

### Retrieve and save the issued VOTable

```python
if len(catalog) == 0:
    raise SystemExit("No catalogue row.")

payload = fetch(catalog["lc_key"][0])
with open("lightcurve.vot", "wb") as handle:
    handle.write(payload)
```

`payload` is the enriched VOTable document. Writing it in binary mode
stores that product on disk. A text or binary VOTable rewrite for a
download button belongs to the application, after `fetch`.

### Read the points as an Astropy Table

The **columns and rows** of the light curve can be loaded with Astropy.
That is not the full issued product: photometry `GROUP`s, `FIELDref`s,
`TIMESYS`, and `COOSYS` do not appear on the `Table`. Facility, filter
identifier, and zero points stay in the VOTable `PARAM`s.

Usual path:

```python
import io
from astropy.table import Table

table = Table.read(io.BytesIO(payload), format="votable")
```

`table.colnames` and `len(table)` are the fields and the number of
epochs. For the OGLE example above this is 167 rows and the columns
`obs_time`, `phot`, `mag_err`, `ogle_phase`. `table.meta` holds only a
few labels (`name`, `description`).

The same columns from Astropy’s VOTable object:

```python
from astropy.io.votable import parse_single_table

vot_table = parse_single_table(io.BytesIO(payload), verify="ignore")
table = vot_table.to_table()
```

`verify="ignore"` avoids treating VOTable 1.5 warnings as failures.
Astropy’s VOTable reader is written for versions 1.1–1.4; this archive
product is 1.5.

## Discovery process and provider notes

[docs/schema.md](docs/schema.md) is the common discovery process. Every provider
follows it. A provider note does not replace it.

[docs/adding_a_lightcurve_provider.md](docs/adding_a_lightcurve_provider.md) is the
checklist for a new plugin.

[docs/mission_lightcurve_providers.md](docs/mission_lightcurve_providers.md)
describes the plugin layout. 

Each file under `docs/providers/` expands the schema for one mission. Empty
sections stay empty until that provider is reviewed.

- [ASAS-SN](docs/providers/asassn.md) (`asassn`)
- [Gaia DR3 AIP](docs/providers/gaia_dr3_aip.md) (`gaia_dr3_aip`)
- [Gaia DR3 ARI](docs/providers/gaia_dr3_ari.md) (`gaia_dr3_ari`)
- [Gaia DR3 VEB](docs/providers/gaia_dr3_veb.md) (`gaia_dr3_veb`)
- [OGLE OCVS](docs/providers/ogle_ocvs.md) (`ogle_ocvs`)
- [Pan-STARRS1 DR2](docs/providers/panstarrs1_dr2.md) (`panstarrs1_dr2`)
- [Personal collections](docs/providers/personal_ts.md) (`personal_ts`)
- [UPJŠ time series](docs/providers/upjs_ts.md) (`upjs_ts`)
- [ZTF](docs/providers/ztf.md) (`ztf`)
