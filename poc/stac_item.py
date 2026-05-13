"""
Generate STAC Item JSONs for Nested-EAGLE forecast outputs.

Each pipeline run produces two outputs:
  1. Raw forecast — full model output (nested global + CONUS grid)
  2. Post-processed — split into separate global (GFS) and CONUS (HRRR 6km) files

STAC Items are written to a dedicated stac/ folder in blob storage,
separate from the data files. MPC Pro's GeoCatalog reads STAC Items
from this folder for ingestion and public distribution.

We will only create STAC and load postprocessed to PC.

Blob layout:
  version/data/raw/{YYYY}/{MM}/{DD}/{HH}/forecast.nc
  version/data/postprocessed/{YYYY}/{MM}/{DD}/{HH}/global.nc
  version/data/postprocessed/{YYYY}/{MM}/{DD}/{HH}/conus.nc
  version/stac/collection.json
  version/stac/items/{YYYY}/{MM}/{DD}/{HH}/postprocessed.json

How to use:
  from stac_item import write_stac_items
  paths = write_stac_items(ic_timestamp, version, output_storage_url)
"""

import json
import os
from datetime import timezone

import pandas as pd

from config import (
    COLLECTION_ID,
    BBOX_CONUS,
    BBOX_GLOBAL,
    VARIABLES,
    PRESSURE_LEVELS,
    LEAD_TIME,
)

COLLECTION_RELATIVE_HREF = "../../../../../stac_collection.json"


def _base_properties(init_utc, forecast_end, version):
    """Shared STAC properties for both raw and post-processed items."""
    return {
        "datetime": None,
        "start_datetime": init_utc.isoformat(),
        "end_datetime": forecast_end.isoformat(),
        "forecast:reference_time": init_utc.isoformat(),
        "forecast:horizon": f"PT{LEAD_TIME}H",
        "forecast:step_hours": 6,
        "nested-eagle:version": version,
        "nested-eagle:variables": VARIABLES,
        "nested-eagle:pressure_levels": PRESSURE_LEVELS,
        "nested-eagle:global_resolution_deg": 0.25,
        "nested-eagle:conus_resolution_km": 6,
    }


def _make_geometry(bbox):
    """Build a GeoJSON Polygon from a bbox."""
    w, s, e, n = bbox
    return {
        "type": "Polygon",
        "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]],
    }


def _stac_links():
    """Links back to the collection (relative paths within stac/ folder)."""
    return [
        {
            "rel": "collection",
            "href": COLLECTION_RELATIVE_HREF,
            "type": "application/json",
        },
        {"rel": "parent", "href": COLLECTION_RELATIVE_HREF, "type": "application/json"},
        {"rel": "root", "href": COLLECTION_RELATIVE_HREF, "type": "application/json"},
    ]


def create_postprocessed_stac_item(
    ic_timestamp: pd.Timestamp,
    version: str,
    output_storage_url,
) -> dict:
    """
    STAC Item for the post-processed forecast (global + CONUS split).

    Assets:
      data/postprocessed/{YYYY}/{MM}/{DD}/{HH}/global.nc  — GFS 0.25° global
      data/postprocessed/{YYYY}/{MM}/{DD}/{HH}/conus.nc   — HRRR 6km CONUS
    """
    init_utc = ic_timestamp.astimezone(timezone.utc)
    folder = init_utc.strftime("%Y/%m/%d/%H")
    forecast_end = init_utc + pd.Timedelta(hours=LEAD_TIME)

    file_name = init_utc.strftime("%Y-%m-%dT%H")

    base_url = output_storage_url.rstrip("/")
    global_href = f"{base_url}/{version}/data/postprocessed/{folder}/nested-global.{file_name}.{LEAD_TIME}h.nc"
    conus_href = f"{base_url}/{version}/data/postprocessed/{folder}/nested-lam.{file_name}.{LEAD_TIME}h.nc"

    return {
        "type": "Feature",
        "stac_version": "1.0.0",
        "id": f"nested-eagle-{init_utc.strftime('%Y%m%d-%H')}z",
        "geometry": _make_geometry(BBOX_GLOBAL),
        "bbox": BBOX_GLOBAL,
        "properties": {
            **_base_properties(init_utc, forecast_end, version),
            "nested-eagle:output_type": "CONUS & Global Domains",
        },
        "collection": COLLECTION_ID,
        "links": _stac_links(),
        "assets": {
            "global": {
                "href": global_href,
                "type": "application/netcdf",
                "title": "Global Forecast (GFS grid, 0.25°)",
                "description": (
                    f"Global forecast on 0.25° grid, "
                    f"{LEAD_TIME}h from {init_utc.strftime('%Y-%m-%d %H:%M')} UTC"
                ),
                "roles": ["data"],
            },
            "conus": {
                "href": conus_href,
                "type": "application/netcdf",
                "title": "CONUS Forecast (HRRR grid, 6km)",
                "description": (
                    f"CONUS regional forecast on 6km grid, "
                    f"{LEAD_TIME}h from {init_utc.strftime('%Y-%m-%d %H:%M')} UTC"
                ),
                "roles": ["data"],
                "proj:bbox": BBOX_CONUS,
            },
        },
    }


def write_stac_items(
    ic_timestamp: pd.Timestamp,
    version: str,
    stac_path,
    output_storage_url,
) -> list[str]:
    """
    Create STAC Items for both raw and post-processed outputs and write
    them to a local stac/items/ folder (mirroring the blob layout).

    Returns list of paths to the written JSON files.
    """
    folder_structure = ic_timestamp.strftime("%Y/%m/%d/%H")
    stac_dir = f"{stac_path}/items/{folder_structure}"
    os.makedirs(stac_dir, exist_ok=True)

    paths = []

    # Post-processed forecast STAC Item
    pp_item = create_postprocessed_stac_item(ic_timestamp, version, output_storage_url)
    pp_path = os.path.join(stac_dir, "postprocessed.json")
    with open(pp_path, "w") as f:
        json.dump(pp_item, f, indent=2)
    print(f"STAC Item written: {pp_path}")
    paths.append(pp_path)

    # collection
    collection_path = os.path.join(stac_path, "stac_collection.json")
    with open("stac_collection.json", "r") as f:
        stac_collection = json.load(f)
    with open(collection_path, "w") as f:
        json.dump(stac_collection, f)

    return paths
