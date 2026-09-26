"""Read an issued light-curve VOTable in package tests.

The discovery package returns bytes. These helpers inspect that product
with Astropy. They do not import the Dash application.
"""

from __future__ import annotations

import io
from types import SimpleNamespace

from astropy.io.votable import parse


class _Scalar:
    """Numeric VOTable parameter wrapped so tests can read ``.value``."""

    def __init__(self, value: float) -> None:
        self.value = value


class _PhotCal:
    """Zero points taken from photDM parameters in one GROUP."""

    def __init__(self, zp_mag: float | None, zp_flux: float | None) -> None:
        self.zp_mag = None if zp_mag is None else _Scalar(float(zp_mag))
        self.zp_flux = None if zp_flux is None else _Scalar(float(zp_flux))


class _PhotDm:
    """Filter identifier and the photcal GROUP shared by its FIELDrefs."""

    def __init__(self, filter_id: str | None, photcal: _PhotCal) -> None:
        self.filter = SimpleNamespace(filter_id=filter_id)
        self.photcal = photcal


class Issued:
    """Columns, table metadata, and photometry groups of one VOTable."""

    def __init__(self, payload: bytes) -> None:
        votable = parse(io.BytesIO(payload))
        resource, table = _first_table(votable)
        self._table = table
        self.colnames = [field.name for field in table.fields]
        self.meta = {param.name: param.value for param in list(resource.params) + list(table.params)}
        self.meta["name"] = table.name
        description = getattr(table, "description", None)
        if description:
            self.meta["description"] = description
        self.photdms = _photdms(votable, table)
        self.coosys = SimpleNamespace(epoch=_coosys_epoch(votable, resource))
        self.table = self

    def __len__(self) -> int:
        return int(self._table.nrows) if self._table.array is not None else 0

    def __getitem__(self, name: str):
        return self._table.array[name]


def load_issued(payload: bytes) -> Issued:
    """Parses issued VOTable bytes.

    Args:
        payload (bytes): Provider product.

    Returns:
        Issued: Columns and photometry parameters.
    """
    return Issued(payload)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _photdms(votable, table) -> dict[str, _PhotDm]:
    """Maps field names to the photcal GROUP that references them."""
    linked: dict[str, _PhotDm] = {}
    groups = []
    for holder in list(votable.resources) + [table]:
        groups.extend(getattr(holder, "groups", []) or [])
    params_by_id = {}
    for holder in list(votable.resources) + [table]:
        for param in getattr(holder, "params", []) or []:
            if getattr(param, "ID", None):
                params_by_id[param.ID] = param
    for group in groups:
        filter_id = _param_value(group, params_by_id, "photDM:PhotometryFilter.identifier")
        zp_flux = _param_value(group, params_by_id, "photDM:PhotCal.zeroPoint.flux.value")
        zp_mag = _param_value(
            group, params_by_id, "photDM:PhotCal.zeroPoint.referenceMagnitude.value"
        )
        if filter_id is None and zp_flux is None and zp_mag is None:
            continue
        photcal = _PhotCal(zp_mag, zp_flux)
        photdm = _PhotDm(filter_id, photcal)
        group_id = getattr(group, "ID", None)
        for entry in group.entries:
            ref = getattr(entry, "ref", None)
            if not ref:
                continue
            for candidate in table.fields:
                if candidate.ID == ref or candidate.name == ref:
                    linked[candidate.name] = photdm
        if group_id:
            for candidate in table.fields:
                if candidate.ref == group_id:
                    linked[candidate.name] = photdm
    return linked


def _param_value(group, params_by_id: dict, utype: str):
    """Returns the first parameter value in a group with this utype."""
    for entry in group.entries:
        if getattr(entry, "utype", None) == utype:
            return entry.value
        ref = getattr(entry, "ref", None)
        param = params_by_id.get(ref)
        if param is not None and param.utype == utype:
            return param.value
    return None


def _first_table(votable):
    """Returns the first resource that contains a TABLE."""
    for resource in votable.resources:
        if resource.tables:
            return resource, resource.tables[0]
    raise ValueError("Issued VOTable has no TABLE")


def _coosys_epoch(votable, resource):
    """Returns the COOSYS epoch when the product publishes one."""
    for holder in (resource, votable):
        iterator = getattr(holder, "iter_coosys", None)
        systems = list(iterator()) if iterator else []
        for coosys in systems:
            epoch = getattr(coosys, "epoch", None)
            if epoch not in (None, ""):
                return float(epoch)
    return None
