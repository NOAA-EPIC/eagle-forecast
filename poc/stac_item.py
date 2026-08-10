"""
Generate STAC Item JSONs for Nested-EAGLE postprocessed outputs.

This module creates two STAC Items per forecast cycle:
  1. Global domain item (nested-eagle-global-...)
  2. CONUS domain item (nested-eagle-conus-...)

Items reference postprocessed NetCDF assets and are written into the AML
`stac_items` output mount, which syncs to the configured datastore path.

Blob layout:
  version/data/postprocessed/{YYYY}/{MM}/{DD}/{HH}/nested-global.{YYYY-MM-DDTHH}.{LEAD_TIME}h.nc
  version/data/postprocessed/{YYYY}/{MM}/{DD}/{HH}/nested-lam.{YYYY-MM-DDTHH}.{LEAD_TIME}h.nc
  version/stac/items/{YYYY}/{MM}/{DD}/{HH}/nested-eagle-global-{YYYYMMDD-HH}z.json
  version/stac/items/{YYYY}/{MM}/{DD}/{HH}/nested-eagle-conus-{YYYYMMDD-HH}z.json

How to use:
  from stac_item import write_stac_items
  paths = write_stac_items(ic_timestamp, version, stac_path, output_storage_url)
"""

import json
import os
from datetime import timezone

import pandas as pd
from config import (
    BBOX_CONUS,
    BBOX_GLOBAL,
    CONUS_COLLECTION_ID,
    GLOBAL_COLLECTION_ID,
    LEAD_TIME,
    PRESSURE_LEVELS,
    VARIABLES,
)
from pyproj import CRS

HRRR_LCC_WKT = CRS.from_cf(
    {
        "grid_mapping_name": "lambert_conformal_conic",
        "standard_parallel": [38.5, 38.5],
        "longitude_of_central_meridian": -97.5,
        "latitude_of_projection_origin": 38.5,
        "earth_radius": 6371229.0,
    }
).to_wkt(version="WKT2_2019")

DATACUBE_EXT = "https://stac-extensions.github.io/datacube/v2.2.0/schema.json"


def _cube_dimensions(bbox):
    """``cube:dimensions`` payload keyed by the coord names cf_patch writes."""
    w, s, e, n = bbox
    return {
        "longitude": {
            "type": "spatial",
            "axis": "x",
            "extent": [w, e],
            "reference_system": 4326,
        },
        "latitude": {
            "type": "spatial",
            "axis": "y",
            "extent": [s, n],
            "reference_system": 4326,
        },
        "time": {"type": "temporal", "extent": [None, None]},
    }


def _cube_dimensions_hrrr():
    """Return datacube dimension metadata for the projected HRRR CONUS grid."""
    return {
        "x": {
            "type": "spatial",
            "axis": "x",
            "extent": [0, 848 - 1],
            "reference_system": HRRR_LCC_WKT,
        },
        "y": {
            "type": "spatial",
            "axis": "y",
            "extent": [0, 480 - 1],
            "reference_system": HRRR_LCC_WKT,
        },
        "time": {"type": "temporal", "extent": [None, None]},
    }


def _cube_variables_hrrr():
    """Describe auxiliary 2D lon/lat variables attached to the HRRR grid."""
    return {
        "longitude": {
            "type": "auxiliary",
            "dimensions": ["y", "x"],
            "unit": "degrees_east",
        },
        "latitude": {
            "type": "auxiliary",
            "dimensions": ["y", "x"],
            "unit": "degrees_north",
        },
    }


def _base_properties(init_utc, forecast_end, version):
    """Shared STAC properties for global and CONUS postprocessed items."""
    return {
        "datetime": None,
        "start_datetime": init_utc.isoformat(),
        "end_datetime": forecast_end.isoformat(),
        "forecast:reference_datetime": init_utc.isoformat(),
        "forecast:horizon": f"PT{LEAD_TIME}H",
        "forecast:duration": "PT6H",
        "nested-eagle:version": version,
        "nested-eagle:variables": VARIABLES,
        "nested-eagle:pressure_levels": PRESSURE_LEVELS,
    }


def _make_geometry(bbox):
    """Build a GeoJSON Polygon from a bbox."""
    w, s, e, n = bbox
    return {
        "type": "Polygon",
        "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]],
    }


def _stac_links_conus():
    """Collection-relative links for the CONUS item."""
    return [
        {
            "rel": "collection",
            "href": "../../../../../stac_collection_conus.json",
            "type": "application/json",
        },
        {
            "rel": "parent",
            "href": "../../../../../stac_collection_conus.json",
            "type": "application/json",
        },
        {
            "rel": "root",
            "href": "../../../../../stac_collection_conus.json",
            "type": "application/json",
        },
    ]


def _stac_links_global():
    """Collection-relative links for the global item."""
    return [
        {
            "rel": "collection",
            "href": "../../../../../stac_collection_global.json",
            "type": "application/json",
        },
        {
            "rel": "parent",
            "href": "../../../../../stac_collection_global.json",
            "type": "application/json",
        },
        {
            "rel": "root",
            "href": "../../../../../stac_collection_global.json",
            "type": "application/json",
        },
    ]


def create_postprocessed_stac_items(
    ic_timestamp: pd.Timestamp,
    version: str,
    output_storage_url,
) -> list[dict]:
    """
    STAC Items for the post-processed forecast.

    Output:
      - Global STAC Item with the global NetCDF asset
      - CONUS STAC Item with the CONUS NetCDF asset
    """
    init_utc = ic_timestamp.astimezone(timezone.utc)
    folder = init_utc.strftime("%Y/%m/%d/%H")
    forecast_end = init_utc + pd.Timedelta(hours=LEAD_TIME)

    file_name = init_utc.strftime("%Y-%m-%dT%H")

    base_url = output_storage_url.rstrip("/")
    global_href = f"{base_url}/{version}/data/postprocessed/{folder}/nested-global.{file_name}.{LEAD_TIME}h.nc"
    conus_href = f"{base_url}/{version}/data/postprocessed/{folder}/nested-lam.{file_name}.{LEAD_TIME}h.nc"

    global_item = {
        "type": "Feature",
        "stac_version": "1.0.0",
        "stac_extensions": [
            "https://stac-extensions.github.io/projection/v1.1.0/schema.json",
            "https://stac-extensions.github.io/datacube/v2.2.0/schema.json",
        ],
        "id": f"nested-eagle-global-{init_utc.strftime('%Y%m%d-%H')}z",
        "geometry": _make_geometry(BBOX_GLOBAL),
        "bbox": BBOX_GLOBAL,
        "properties": {
            **_base_properties(init_utc, forecast_end, version),
            "nested-eagle:output_type": "Nested-EAGLE Global Domain",
            "nested-eagle:global_resolution_deg": 0.25,
        },
        "collection": GLOBAL_COLLECTION_ID,
        "links": _stac_links_global(),
        "assets": {
            "global": {
                "href": global_href,
                "type": "application/netcdf",
                "msft:ingestion": {"virtualize": "kerchunk"},
                "title": "Global Forecast (0.25°)",
                "description": (
                    f"Global forecast on 0.25° grid, "
                    f"{LEAD_TIME}h from {init_utc.strftime('%Y-%m-%d %H:%M')} UTC"
                ),
                "proj:epsg": 4326,
                "cube:dimensions": _cube_dimensions(BBOX_GLOBAL),
            },
        },
    }

    conus_item = {
        "type": "Feature",
        "stac_version": "1.0.0",
        "stac_extensions": [
            "https://stac-extensions.github.io/projection/v1.1.0/schema.json",
            "https://stac-extensions.github.io/datacube/v2.2.0/schema.json",
        ],
        "id": f"nested-eagle-conus-{init_utc.strftime('%Y%m%d-%H')}z",
        "geometry": _make_geometry(BBOX_CONUS),
        "bbox": BBOX_CONUS,
        "properties": {
            **_base_properties(init_utc, forecast_end, version),
            "nested-eagle:output_type": "Nested-EAGLE CONUS Domain",
            "nested-eagle:conus_resolution_km": 6,
        },
        "collection": CONUS_COLLECTION_ID,
        "links": _stac_links_conus(),
        "assets": {
            "conus": {
                "href": conus_href,
                "type": "application/netcdf",
                "msft:ingestion": {"virtualize": "kerchunk"},
                "title": "CONUS Forecast (6km)",
                "description": (
                    f"CONUS regional forecast on 6km grid, "
                    f"{LEAD_TIME}h from {init_utc.strftime('%Y-%m-%d %H:%M')} UTC"
                ),
                "proj:shape": [480, 848],
                "proj:epsg": None,
                "proj:wkt2": HRRR_LCC_WKT,
                "cube:dimensions": _cube_dimensions_hrrr(),
                "cube:variables": _cube_variables_hrrr(),
            },
        },
    }

    return [global_item, conus_item]


def write_stac_items(
    ic_timestamp: pd.Timestamp,
    version: str,
    stac_path,
    output_storage_url,
) -> list[str]:
    """
    Create postprocessed STAC Items and write them to `stac/items/...`.

    Returns:
        list[str]: Absolute paths to the written item JSON files.
    """
    folder_structure = ic_timestamp.strftime("%Y/%m/%d/%H")
    stac_dir = os.path.join(stac_path, "items", folder_structure)
    os.makedirs(stac_dir, exist_ok=True)

    paths = []

    items = create_postprocessed_stac_items(
        ic_timestamp,
        version,
        output_storage_url,
    )

    for item in items:
        item_id = item["id"]
        item_path = os.path.join(stac_dir, f"{item_id}.json")

        with open(item_path, "w", encoding="utf-8") as f:
            json.dump(item, f, indent=2)

        print(f"STAC Item written: {item_path}")
        paths.append(item_path)

    return paths
