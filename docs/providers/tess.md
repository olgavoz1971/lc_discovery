# TESS archive (`tess`)

Expands [schema.md](../schema.md). MAST pipeline light curves via Lightkurve.
FFI/TPF cutouts are not this plugin.

Registered as `tess`. FFI/TPF cutouts remain out of scope.

## 1. Discovery

TIC lookup is the same pattern as Gaia `source_id`: `TIC 159717514`,
`TIC:159717514`, or a bare integer of at least six digits. Simbad
cross-identifiers are scanned for a TIC.

Cone search calls Lightkurve `search_lightcurve` with `mission='TESS'`.
Every product in the cone is kept. The closest TIC is not selected. The
maximum cone radius is **10 arcmin**. Cone results are capped at **500**
catalogue rows. A TIC lookup is not truncated by that cap.

One catalogue row is one MAST product, unique on TIC + sector + author +
`exptime`. `exptime` is the MAST cadence (seconds), not CRM live time.

`object_name` is `TIC <n>`. `filter_name` is the passband `TESS` (FPS
`TESS/TESS.Red`), not the product identity.

Product identity for the **results table** uses the locked extra-column
hook ([schema.md](../schema.md)), not new core fields. TESS declares three
extras (default for other missions: none):

| Header | Row value (example) |
| --- | --- |
| Sector | `16` |
| Exp | `120s` — MAST cadence |
| Author | `SPOC` |

`lc_key` payload remains `tic`, `sector`, `author`, `exptime` for fetch.
That payload is not a grid column.

`mag` is MAST `tmag` when present. `t_min` / `t_max` are MAST coverage
when present.

Discovery lists **every** MAST author. The column registry is not an
allow-list. A new pipeline appears in the table like SPOC.

Choosing a default working series, and checking that the issued table has
the minimum columns the caller needs (time, a flux or magnitude column), is
the **caller's** job, not this plugin's. This plugin
does not pick SAP vs PDCSAP at fetch, and it does not refuse a product
because it lacks a flux column. It issues what the archive delivered.

## 2. Retrieval

Lightkurve search with those four fields must return exactly one product.
Other authors are downloaded with `SearchResult.download()` and Lightkurve
defaults.

### 2.1 Authors read by the generic reader (TARS)

Lightkurve is still used for TARS: search is `lk.search_lightcurve`, and the
file is read with `lk.read`, which returns a normal `LightCurve`
(`time`, `flux`, `flux_err`). Only the download step differs.

`SearchResult.download()` always passes `quality_bitmask` to the file reader.
The generic HLSP reader used for TARS does not accept that argument, so
`download()` fails with "Error in reading Data product ... of type generic"
(the message suggests a corrupt download, which is misleading; the file is
fine). Lightkurve offers no public way to switch the argument off.

For authors listed in `config.GENERIC_READER_AUTHORS` the plugin therefore:

1. fetches the file with `astroquery.mast.Observations.download_products`
   (the same call `download()` makes internally) into the Lightkurve cache
   directory (`lightkurve.config.get_cache_dir()`);
2. reads it with `lk.read(path)` without `quality_bitmask`.

Consequences: the plugin depends on the `download_products` signature
(already a Lightkurve dependency), and Lightkurve's own shortcut for files
already in its cache is skipped (astroquery does its own cache check). The
generic reader provides no quality column, so no quality filtering is
applied to these products. If Lightkurve later makes the generic reader
accept `quality_bitmask`, the special case can be removed.

### 2.2 Cache and refresh

The FITS file lives in the Lightkurve cache (`lightkurve.config.get_cache_dir()`),
so every caller on the machine shares it. A cache hit does no network
call. A truncated cached file is purged and downloaded once more.

- `fetch(lc_key, force_refresh=True)` deletes the file of that product and
  downloads it again.
- `purge_cache(lc_key)` deletes the file only.

Both search MAST once to identify the one product (TIC, sector, author,
`exptime`), then act on that file. No other file is touched. The VOTable is
built at every `fetch`; it is not cached.

## 3. What we change

The archive FITS is not returned. The issued VOTable is built here.

Principle: this plugin **discovers and makes data more VO-compatible as far
as it can**. It never throws away a column it does not understand. A column
without a known role is issued as is (no UCD, no PhotCal). Whether the
result is usable (time and photometry present) is decided later, in the
caller, which raises a clear error when it is not.

Time: Lightkurve `TIME` is BTJD (JD − 2457000). Issued `time` is MJD,
UCD `time.epoch` (**time** role), TIMESYS TDB / BARYCENTER /
`timeorigin=2400000.5`. Those values are **checked against the Lightkurve
time object** (`format` BTJD, `scale` TDB). A product reported with another
format or scale raises an explicit error. FITS time keywords are not used
for this check: they describe the raw file, which Lightkurve readers may
convert (CDIPS stores BJD and is read as BTJD).

Column **roles** are how we decide UCDs.
Names are not the contract. Roles used here: **time**, **flux**, **error**,
**background**.

The author/column registry exists only to (a) know those roles for
**reviewed** pipelines, and (b) attach documented PhotCal. It does not
hide products at discovery.

**Background UCDs never contain `phot.flux`**, so that a caller looking for
photometry cannot mistake background for target flux: background is
`instr.background`, its error `stat.error;instr.background`.

**PhotCal 20.44 is decided from the file, not from the author.** For any
flux-role column, known or unknown author, the zero point flux
`1 electron s-1` / ZP mag `20.44` is attached only when the column unit read
from the product is electron s-1 family or counts per second (see 3.2).
A known author whose file declares another unit gets passband only.

### 3.1 Known author

Every registry **flux** and **background** column that exists in the file
is kept (SAP and PDCSAP together when both exist). There is no “default
flux” choice in this plugin.

PhotCal:

| Author | Target flux | Zero points |
| --- | --- | --- |
| SPOC, TESS-SPOC | `pdcsap_flux`, `sap_flux`. FITS/Lightkurve unit is **electron s-1** (`e-/s`, photoelectrons per second), not counts/s | ZP flux `1 electron s-1`, ZP mag `20.44` (config), only when the file unit is that family |
| QLP, TARS | dimensionless flux columns | TESSMAG when finite; otherwise passband only |
| TASOC `flux_corr` | dimensionless | passband only |
| TASOC `flux_raw`, Eleanor | electron s-1 | passband only (no 20.44) |
| TGLC | `cal_psf_flux` | GAIAMAG when finite; otherwise passband only |
| Background (`sap_bkg`, `flux_bkg`, …) | **background** role, not target photometry | passband only; no magnitude zero point. UCD `instr.background` (error `stat.error;instr.background`); no `phot.flux` |

Filter identifier `TESS/TESS.Red`, effective wavelength 7453 Å. TARS
`PER1` / `TMIN1` become `period` (days) and `epoch` (absolute JD) when
present.

### 3.2 Unknown author (not in the registry)

Keep **every** column from the Lightkurve table. Do not invent column
names. Do not omit the product at search or at fetch. A column that cannot
be understood is issued as is: its name, unit and values, no UCD, no
PhotCal. It is never dropped.

**Roles come from what Lightkurve declares, not from a name whitelist.**
A Lightkurve `LightCurve` always has the primary `flux` and `flux_err`
columns. They are the reader's own statement of which archive columns are
the target flux and its error. The archive column they were taken from is
recorded by Lightkurve in the metadata (`FLUX_ORIGIN`). Roles:

| Role | How we know it | UCD written |
| --- | --- | --- |
| time | the issued time column (`time`) | `time.epoch` |
| flux | the Lightkurve `flux` column, issued under the archive column named in `FLUX_ORIGIN` | `phot.flux` |
| error | the Lightkurve `flux_err` column, issued under its archive name, same group as its flux | `stat.error;phot.flux` |
| background | names classified as background by the registry (including background error) | `instr.background` or `stat.error;instr.background` |
| none | anything else | no UCD |

Other flux-like columns of an unknown pipeline (for example a second
photometry column that Lightkurve does not mark as `flux`) get no role and
are issued as is. If `FLUX_ORIGIN` is absent or names no column, the flux
role is not assigned and the product is still issued as is. Name matching
against the registry is used only for background, never to guess flux.
Names are not the contract.

**PhotCal on flux-role columns.** Passband metadata is always attached
(`TESS/TESS.Red`, 7453 Å). Zero points use the **unit read from the
product**, for known and unknown authors alike:

- If the unit is electron s-1 (`electron s-1`, `e-/s`, `electron/s`) **or**
  counts per second (`ct/s`, `count/s`, `counts/s`) use the instrument
  pair ZP flux `1 electron s-1`, ZP mag **20.44**.
- Otherwise (dimensionless, ppm, missing unit, anything else): passband
  only; no 20.44.

Background-role columns never get 20.44, even when the unit is electron
s-1.

**Column types.** Every issued column keeps its real datatype. Numeric
columns are `double`/`int`. Non-numeric columns (strings, flags that cannot
be read as numbers) are issued with their true VOTable datatype, not coerced
to `double`. Units that VOTable cannot express are not written; the column
is still issued.

## 4. Responsibility split

| Question | Answered by |
| --- | --- |
| What did the archive deliver, and what can be labelled? | this plugin |
| Is time present, and does it claim BTJD/TDB consistently? | this plugin (explicit error on contradiction) |
| Is there a time column and a flux or magnitude column the application can use? Which one is the default working series? | the caller, with a clear error when the minimum is missing |
