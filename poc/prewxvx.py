"""Convert and annotate forecast outputs into final NetCDF delivery files."""

import gc
import logging
import os

import anemoi.datasets
import eagle.tools
import numpy as np
import pandas as pd
import tiler
import xarray as xr
from eagle.tools.data import open_anemoi_inference_dataset, open_forecast_zarr_dataset
from eagle.tools.nested import prepare_regrid_target_mask
from ufs2arco.transforms.horizontal_regrid import horizontal_regrid

logger = logging.getLogger("eagle.tools")


def main(config):
    """Run the prewxvx conversion workflow from a config path or dict."""
    if isinstance(config, str):
        from eagle.tools.utils import setup

        config = setup(config, "prewxvx")

    topo = config["topo"]

    forecast_path = config["forecast_path"]
    output_path = config["output_path"]
    model_type = config["model_type"]
    from_anemoi = config.get("from_anemoi", True)
    lead_time = config["lead_time"]

    open_kwargs = {
        "load": True,
        "reshape_cell_to_2d": True,
        "levels": config.get("levels", None),
        "vars_of_interest": config.get("vars_of_interest", None),
        "member": config.get("member", None),
        "lcc_info": config.get("lcc_info", None),
        "rename_to_longnames": config.get("rename_to_longnames", False),
    }

    if model_type == "nested-global":
        config["forecast_regrid_kwargs"]["target_grid_path"], mask = (
            prepare_regrid_target_mask(
                anemoi_reference_dataset_kwargs=config[
                    "anemoi_reference_dataset_kwargs"
                ],
                horizontal_regrid_kwargs=config["forecast_regrid_kwargs"],
            )
        )

    dates = pd.date_range(config["start_date"], config["end_date"], freq=config["freq"])
    n_dates = len(dates)
    n_batches = int(np.ceil(n_dates / topo.size))
    for batch_idx in range(n_batches):
        date_idx = (batch_idx * topo.size) + topo.rank
        if date_idx + 1 > n_dates:
            break  # Last batch situation

        try:
            t0 = dates[date_idx]
        except:
            logger.error(f"Error getting this date: {date_idx} / {n_dates}")
            raise

        st0 = t0.strftime("%Y-%m-%dT%H")
        logger.info(f"Processing {st0}")

        path_in = f"{forecast_path}/{st0}.{lead_time}h.nc"
        path_out = f"{output_path}/{model_type}.{st0}.{lead_time}h.nc"

        logger.info(f"Opening {path_in}")
        if from_anemoi:
            xds = open_anemoi_inference_dataset(
                path=path_in,
                model_type=model_type,
                lam_index=config.get("lam_index", None),
                horizontal_regrid_kwargs=config.get("forecast_regrid_kwargs", None),
                **open_kwargs,
            )
        else:
            xds = open_forecast_zarr_dataset(
                config["forecast_path"],
                t0=t0,
                trim_edge=config.get("trim_forecast_edge", None),
                **open_kwargs,
            )

        xds.attrs = {}
        if "lam" in model_type and config.get(
            "rename_curvilinear_coords_to_latlon", True
        ):
            for key in ["x", "y"]:
                if key in xds.coords:
                    xds = xds.drop_vars(key)
            xds = xds.rename({"x": "longitude", "y": "latitude"})

        if model_type == "nested-global":
            xds["nest_mask"] = mask.rename({"lat": "latitude", "lon": "longitude"})
            xds["nest_mask"].attrs = {
                "long_name": "Nest mask",
                "description": "Binary mask. 1 = grid cell is in the nested region, 0 = rest of the globe",
            }
            xds = xds.set_coords("nest_mask")

        # planetary computer requires -180/180
        if "longitude" in xds.coords:
            xds = xds.assign_coords(longitude=((xds.longitude + 180) % 360) - 180)

        # Attributes
        xds.attrs["forecast_reference_time"] = str(xds.time.values[0])

        user_attributes = config.get("attributes", {})
        xds.attrs.update(user_attributes.get("dataset", {}))
        for varname, var_attrs in user_attributes.get("variables", {}).items():
            if varname in xds:
                xds[varname].attrs.update(var_attrs)
            else:
                logger.warning(
                    f"Variable '{varname}' not found in dataset, skipping attributes"
                )

        # Add descriptive meta info for diagnostic fields, which have all NaNs in the first timestamp
        for varname in xds.data_vars:
            t0 = xds[varname].isel(time=0)
            num_nans = np.isnan(t0).sum().values
            num_cell = np.prod(t0.shape)
            if num_nans == num_cell:
                logger.info(f"Found diagnostic {varname}")
                note = xds[varname].attrs.get("diagnostic_note", "")
                if len(note) > 0:
                    note += " "
                note += f"{varname} is diagnosed by the model, so the initial condition is all NaNs"
                xds[varname].attrs["diagnostic_note"] = note

        # Sort the data variables and levels
        xds = xds[sorted(xds.data_vars)]
        xds = xds.sortby("level")

        if model_type == "nested-global":
            xds = xds.sortby("longitude")

        # metadata for PC
        if model_type == "nested-lam":
            crs = xr.DataArray(
                np.int32(0),
                attrs={
                    "grid_mapping_name": "lambert_conformal_conic",
                    "standard_parallel": [38.5, 38.5],
                    "longitude_of_central_meridian": -97.5,
                    "latitude_of_projection_origin": 38.5,
                    "earth_radius": 6371229.0,
                },
            )
            xds = xds.assign_coords(crs=crs)
            for v in xds.data_vars:
                xds[v].attrs["grid_mapping"] = "crs"
                xds[v].attrs["coordinates"] = "latitude longitude"

            xds = tiler.reconstruct_projected_coordinates(ds=xds)

        xds.attrs["Conventions"] = "CF-1.8"

        # Chunking
        # One time step + one pressure level per chunk; full spatial extent.
        # This matches the tiler's sel=time=... / sel=level=... access pattern.
        xds = xds.chunk({"time": 1, "level": 1})
        encoding = {}
        for name, da in xds.data_vars.items():
            if not da.dims:  # skip scalars (e.g. crs in conus.nc)
                continue
            encoding[name] = {
                "chunksizes": tuple(da.chunksizes[d][0] for d in da.dims),
                "zlib": True,
                "complevel": 1,
                "dtype": da.dtype,
            }
            # Preserve the CRS reference added by rioxarray.
            if "grid_mapping" in da.encoding:
                encoding[name]["grid_mapping"] = da.encoding["grid_mapping"]
        for name, enc in encoding.items():
            da = xds[name]
            print(f"  {name:<35} {str(da.shape):<30} {enc['chunksizes']}")

        xds.to_netcdf(path_out, engine="h5netcdf", encoding=encoding)

        logger.info(f"Wrote to {path_out}")

        try:
            xds.close()
        except Exception:
            pass

        del xds
        try:
            del t0
        except NameError:
            pass

        gc.collect()

    logger.info(f"Done with prewxvx workflow")
