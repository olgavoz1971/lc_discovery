"""Tests for the TESS archive cache: classification, repair policy, opening."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits
from astropy.table import Table
from lightkurve import LightkurveError

from lc_discovery.providers.tess import archive_cache


def _lk_error_from_cause(cause: BaseException) -> LightkurveError:
    """Returns a LightkurveError with ``__cause__`` set like ``raise ... from``."""
    try:
        raise LightkurveError(
            "Error in reading Data product /tmp/x.fits of type generic .\n"
            "This file may be corrupt due to an interrupted download. "
            "Please remove it from your disk and try again."
        ) from cause
    except LightkurveError as exc:
        return exc


class _OneRow:
    """Minimal one-row search result."""

    def __init__(self):
        self.table = Table(
            {
                "obs_collection": ["TESS"],
                "obs_id": ["tess123"],
                "productFilename": ["f_lc.fits"],
            }
        )

    def __len__(self):
        return 1


def test_generic_quality_bitmask_is_unsupported():
    """Generic reader TypeError is not a truncated cache."""
    exc = _lk_error_from_cause(
        TypeError("read_generic_lightcurve() got an unexpected keyword argument 'quality_bitmask'")
    )
    assert archive_cache.classify_failure(exc) == "unsupported_product"


def test_buffer_too_small_is_truncated():
    """NumPy buffer error is a truncated FITS."""
    exc = _lk_error_from_cause(TypeError("buffer is too small for requested array"))
    assert archive_cache.classify_failure(exc) == "truncated_cache"


def test_canned_sentence_alone_is_other():
    """Lightkurve's canned sentence must not trigger a purge."""
    exc = LightkurveError(
        "Not recognized as a supported data product:\n/tmp/x.fits\n"
        "This file may be corrupt due to an interrupted download."
    )
    assert archive_cache.classify_failure(exc) == "other"


def test_format_unsupported_omits_corrupt_claim():
    """Message names the author and does not claim corruption."""
    exc = _lk_error_from_cause(
        TypeError("read_generic_lightcurve() got an unexpected keyword argument 'quality_bitmask'")
    )
    message = archive_cache.format_failure(exc, author="TARS")
    assert "TARS" in message
    assert "corrupt" not in message.lower()
    assert "left unchanged" in message


def test_format_other_strips_canned_sentence():
    """Inner text is kept without the canned paragraph."""
    exc = _lk_error_from_cause(ValueError("No reference time found in /tmp/x.fits."))
    message = archive_cache.format_failure(exc, author="SPOC")
    assert "No reference time found" in message
    assert "interrupted download" not in message.lower()


def test_unsupported_failure_does_not_purge(monkeypatch):
    """An unsupported product keeps its cached file and raises once."""
    calls = {"purge": 0, "open": 0}
    monkeypatch.setattr(archive_cache, "ensure_fits", lambda _s: "/x.fits")
    monkeypatch.setattr(
        archive_cache, "purge", lambda _p: calls.__setitem__("purge", calls["purge"] + 1)
    )

    def _open(_path):
        calls["open"] += 1
        raise _lk_error_from_cause(TypeError("unexpected keyword argument 'quality_bitmask'"))

    monkeypatch.setattr(archive_cache, "open_product", _open)
    with pytest.raises(ValueError, match="left unchanged"):
        archive_cache.read_with_repair(_OneRow(), author="TARS")
    assert calls == {"purge": 0, "open": 1}


def test_truncated_failure_purges_once_and_retries(monkeypatch):
    """A truncated file is purged and read again exactly once."""
    calls = {"purge": 0, "open": 0}
    monkeypatch.setattr(archive_cache, "ensure_fits", lambda _s: "/x.fits")
    monkeypatch.setattr(
        archive_cache, "purge", lambda _p: calls.__setitem__("purge", calls["purge"] + 1)
    )

    class _LC:
        meta = {}

    def _open(_path):
        calls["open"] += 1
        if calls["open"] == 1:
            raise _lk_error_from_cause(TypeError("buffer is too small for requested array"))
        return _LC()

    monkeypatch.setattr(archive_cache, "open_product", _open)
    lc, pointer = archive_cache.read_with_repair(_OneRow(), author="SPOC")
    assert calls == {"purge": 1, "open": 2}
    assert lc.meta["AUTHOR"] == "SPOC"
    assert pointer["product_filename"] == "f_lc.fits"


def _write_generic_lc_fits(path: Path, *, include_flux: bool) -> None:
    """Writes a minimal TESS-like table FITS for generic-reader tests.

    Args:
        path (Path): Output path.
        include_flux (bool): When false, omit the FLUX column.
    """
    data = {"TIME": np.array([1000.0, 1001.0])}
    if include_flux:
        data["FLUX"] = np.array([1.0, 1.1])
    hdu = fits.BinTableHDU(Table(data), name="LIGHTCURVE")
    hdu.header["BJDREFI"] = 2457000
    hdu.header["TUNIT1"] = "d"
    hdu.header["TIMESYS"] = "tdb"
    primary = fits.PrimaryHDU()
    primary.header["TELESCOP"] = "TESS"
    primary.header["TIMESYS"] = "TDB"
    fits.HDUList([primary, hdu]).writeto(path, overwrite=True)


def test_open_generic_product_without_quality_bitmask(tmp_path):
    """Generic TIME+FLUX FITS opens without quality_bitmask."""
    path = tmp_path / "generic_lc.fits"
    _write_generic_lc_fits(path, include_flux=True)
    lc = archive_cache.open_product(str(path))
    assert "flux" in lc.colnames
    assert len(lc) == 2


def test_open_generic_product_refuses_missing_flux(tmp_path):
    """Generic FITS without FLUX is refused with an unsupported message."""
    path = tmp_path / "no_flux.fits"
    _write_generic_lc_fits(path, include_flux=False)
    with pytest.raises(ValueError, match="not a recognised tess pipeline"):
        archive_cache.open_product(str(path))


def test_pointer_path_under_mast_download(tmp_path, monkeypatch):
    """The pointer resolves to mastDownload/<collection>/<obs_id>/<file>."""
    monkeypatch.setattr(archive_cache, "cache_dir", lambda: str(tmp_path))
    pointer = archive_cache.product_pointer(_OneRow())
    assert archive_cache.pointer_path(pointer) == str(
        tmp_path / "mastDownload" / "TESS" / "tess123" / "f_lc.fits"
    )


def test_purge_removes_file_and_reports_missing(tmp_path, monkeypatch):
    """Purge deletes an existing file and returns False when absent."""
    monkeypatch.setattr(archive_cache, "cache_dir", lambda: str(tmp_path))
    pointer = archive_cache.product_pointer(_OneRow())
    assert archive_cache.purge(pointer) is False
    dest = Path(archive_cache.pointer_path(pointer))
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"x")
    assert archive_cache.purge(pointer) is True
    assert not dest.exists()
