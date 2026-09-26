# Lightcurve discovery

Stub. The contract is not written yet. This folder holds the discovery
documents until they move into the extracted package.

## Project-wide

[schema.md](schema.md) is the common discovery process. Every provider
follows it. A provider note does not replace it.

[mission_lightcurve_providers.md](mission_lightcurve_providers.md) is the
application architecture (page, registry, `CurveDash` boundary).

[adding_a_lightcurve_provider.md](adding_a_lightcurve_provider.md) is the
checklist for adding a plugin in this repository.

## Provider notes

Each file expands the common schema for one provider. Empty sections stay
empty until that provider is reviewed.

- [ASAS-SN](providers/asassn.md) (`asassn`)
- [Gaia DR3 AIP](providers/gaia_dr3_aip.md) (`gaia_dr3_aip`)
- [Gaia DR3 ARI](providers/gaia_dr3_ari.md) (`gaia_dr3_ari`)
- [Gaia DR3 VEB](providers/gaia_dr3_veb.md) (`gaia_dr3_veb`)
- [OGLE OCVS](providers/ogle_ocvs.md) (`ogle_ocvs`)
- [Pan-STARRS1 DR2](providers/panstarrs1_dr2.md) (`panstarrs1_dr2`)
- [Personal collections](providers/personal_ts.md) (`personal_ts`)
- [UPJŠ time series](providers/upjs_ts.md) (`upjs_ts`)
- [ZTF](providers/ztf.md) (`ztf`)
