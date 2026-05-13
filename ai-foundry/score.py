"""
Azure ML managed online endpoint scoring script for Nested-EAGLE.

Contract:
    init()  — called once at container startup; loads the checkpoint
    run()   — called per request; accepts initial conditions, returns forecast path

Request body (JSON):
    {
        "gfs_zarr_path":  "<az://> or local path to GFS zarr",
        "hrrr_zarr_path": "<az://> or local path to HRRR zarr (regridded to 6km)",
        "ic_timestamp":   "2026-04-20T00",   // ISO8601, 6-hourly
        "lead_time":      240                // forecast hours (default 240)
    }

Response body (JSON):
    {
        "status":       "success",
        "forecast_nc":  "/tmp/output/<ic_timestamp>/forecast.nc",
        "global_nc":    "/tmp/output/<ic_timestamp>/postprocessed/global.nc",
        "conus_nc":     "/tmp/output/<ic_timestamp>/postprocessed/conus.nc"
    }

Environment variables (set via AML endpoint deployment):
    CHECKPOINT_PATH   — path to inference-last.ckpt (mounted via AML model mount)
    GRID_FILE         — path to hrrr_06km.nc (mounted alongside checkpoint)

Usage as AML managed online endpoint:
    See ai-foundry/README.md for deployment steps.
"""

import json
import os
import sys
import tempfile
import traceback

import numpy as np
import pandas as pd
import xarray as xr

# AML inference SDK — available in azureml-defaults
import azureml.core

from eagle.tools.inference import main as eagle_inference

# Optional: postproc for splitting into global + CONUS
sys.path.insert(0, os.path.dirname(__file__))
import postproc

# --- Global state set in init() ---
CHECKPOINT_PATH = None
GRID_FILE = None
OUTPUT_ROOT = "/tmp/nested-eagle-output"


def init():
    """
    Called once when the container starts. Loads configuration from environment.
    The checkpoint itself is loaded lazily by anemoi-inference on first call.
    """
    global CHECKPOINT_PATH, GRID_FILE

    CHECKPOINT_PATH = os.environ.get("CHECKPOINT_PATH", "/mnt/models/inference-last.ckpt")
    GRID_FILE = os.environ.get("GRID_FILE", "/mnt/models/hrrr_06km.nc")

    if not os.path.exists(CHECKPOINT_PATH):
        raise FileNotFoundError(
            f"Checkpoint not found at {CHECKPOINT_PATH}. "
            "Set CHECKPOINT_PATH env var or mount the AML model to /mnt/models/."
        )

    os.makedirs(OUTPUT_ROOT, exist_ok=True)
    print(f"[init] Checkpoint: {CHECKPOINT_PATH}")
    print(f"[init] Grid file:  {GRID_FILE}")
    print("[init] Nested-EAGLE scoring script ready.")


def run(raw_data):
    """
    Called per inference request. Accepts JSON, returns JSON.

    raw_data: str — JSON string with gfs_zarr_path, hrrr_zarr_path, ic_timestamp, lead_time
    """
    try:
        data = json.loads(raw_data)

        gfs_zarr_path  = data["gfs_zarr_path"]
        hrrr_zarr_path = data["hrrr_zarr_path"]
        ic_timestamp   = pd.Timestamp(data["ic_timestamp"])
        lead_time      = int(data.get("lead_time", 240))

        folder     = ic_timestamp.strftime("%Y/%m/%d/%H")
        output_dir = os.path.join(OUTPUT_ROOT, folder)
        os.makedirs(output_dir, exist_ok=True)

        # Build anemoi-inference config
        config = {
            "checkpoint_path": CHECKPOINT_PATH,
            "lead_time": lead_time,
            "start_date": ic_timestamp.strftime("%Y-%m-%dT%H"),
            "end_date":   ic_timestamp.strftime("%Y-%m-%dT%H"),
            "freq": "6h",
            "input_dataset_kwargs": {
                "cutout": [
                    {
                        "dataset": hrrr_zarr_path,
                        "trim_edge": [25, 24, 25, 26],
                    },
                    {
                        "dataset": gfs_zarr_path,
                    },
                ],
                "adjust": "all",
                "min_distance_km": 6,
            },
            "output_path": output_dir,
        }

        # Run inference
        print(f"[run] Running eagle_inference for {ic_timestamp} ...")
        eagle_inference(config)

        forecast_nc = os.path.join(output_dir, "forecast.nc")
        if not os.path.exists(forecast_nc):
            return json.dumps({
                "status": "error",
                "message": f"eagle_inference completed but forecast.nc not found at {forecast_nc}"
            })

        # Post-process: split into global.nc + conus.nc
        print("[run] Post-processing ...")
        postproc.postprocess_forecast(
            version=OUTPUT_ROOT,
            grid_file=GRID_FILE,
            ic_timestamp=ic_timestamp,
        )

        global_nc = os.path.join(OUTPUT_ROOT, "postprocessed", folder, "global.nc")
        conus_nc  = os.path.join(OUTPUT_ROOT, "postprocessed", folder, "conus.nc")

        return json.dumps({
            "status":      "success",
            "forecast_nc": forecast_nc,
            "global_nc":   global_nc if os.path.exists(global_nc) else None,
            "conus_nc":    conus_nc  if os.path.exists(conus_nc)  else None,
        })

    except KeyError as e:
        return json.dumps({
            "status":  "error",
            "message": f"Missing required field: {e}. "
                       "Expected: gfs_zarr_path, hrrr_zarr_path, ic_timestamp"
        })
    except Exception as e:
        return json.dumps({
            "status":  "error",
            "message": str(e),
            "trace":   traceback.format_exc(),
        })
