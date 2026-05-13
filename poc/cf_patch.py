"""
Patch a NetCDF file in-place to add CF-compliant axis metadata so
Planetary Computer Pro's data-cube ingestion transformer can identify
X/Y/T dimensions without ambiguity.

Background:
    GeoCatalog's cube transformer falls back to ``cf_xarray.guess_coord_axis``
    when the per-asset ``xarray:open_kwargs`` aren't honored. That fallback
    raises ``KeyError: 'X'`` if the coordinate variables lack CF attributes
    (``axis``, ``standard_name``, ``units``). The fix is to tag the
    horizontal + time coords on the NetCDF itself.
"""

from __future__ import annotations

import os

import xarray as xr


# Common coordinate-name conventions we may encounter in the output files.
_X_NAMES = ("lon", "longitude", "x", "X", "nav_lon")
_Y_NAMES = ("lat", "latitude", "y", "Y", "nav_lat")
_T_NAMES = ("time", "t", "valid_time", "forecast_time")


def _pick(ds: xr.Dataset, candidates: tuple[str, ...]) -> str | None:
    for name in candidates:
        if name in ds.variables or name in ds.coords or name in ds.dims:
            return name
    return None


def add_cf_metadata(path: str) -> dict[str, str]:
    """
    Open ``path``, add CF ``axis`` / ``standard_name`` / ``units`` attrs to
    the horizontal + time coordinates, then re-write the file in-place.

    Returns a dict like ``{"x": "lon", "y": "lat", "t": "time"}`` so the
    caller can use the same names when building the STAC item.
    """
    ds = xr.open_dataset(path)

    x_name = _pick(ds, _X_NAMES)
    y_name = _pick(ds, _Y_NAMES)
    t_name = _pick(ds, _T_NAMES)

    if x_name is None or y_name is None:
        ds.close()
        raise ValueError(
            f"Could not identify X/Y coordinates in {path}. "
            f"Found coords: {list(ds.coords)} dims: {list(ds.dims)}"
        )

    # Load into memory so we can re-write to the same path safely.
    ds = ds.load()

    ds[x_name].attrs.update(
        {"axis": "X", "standard_name": "longitude", "units": "degrees_east"}
    )
    ds[y_name].attrs.update(
        {"axis": "Y", "standard_name": "latitude", "units": "degrees_north"}
    )
    if t_name is not None:
        ds[t_name].attrs.update({"axis": "T", "standard_name": "time"})

    # Mark Conventions on the dataset itself.
    conv = ds.attrs.get("Conventions", "")
    if "CF-" not in conv:
        ds.attrs["Conventions"] = (conv + " CF-1.8").strip()

    tmp = path + ".cfpatch.tmp"
    ds.to_netcdf(tmp)
    ds.close()
    os.replace(tmp, path)

    return {"x": x_name, "y": y_name, "t": t_name or ""}
