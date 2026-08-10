"""Postprocess forecast outputs, generate STAC items, and ingest to GeoCatalog."""

import argparse
import os

import pc_ingest
import prewxvx
import stac_item
import utils
import yaml
from config import (
    CONUS_COLLECTION_ID,
    GEOCATALOG_URL,
    GLOBAL_COLLECTION_ID,
    MIN_DISTANCE_KM,
    OUTPUT_STORAGE_URL,
    TRIM_EDGE,
    VERSION,
)


def prep_config(
    model_name,
    ic_timestamp,
    output_path,
    initial_conditions,
    raw_inference,
    trim_edge=TRIM_EDGE,
    min_distance_km=MIN_DISTANCE_KM,
):
    """Create a postprocessing config for either nested-lam or nested-global."""
    config = utils.load_config(f"config/{model_name}.yaml")

    folder_structure = ic_timestamp.strftime("%Y/%m/%d/%H")

    config["start_date"] = ic_timestamp.strftime("%Y-%m-%dT%H")
    config["end_date"] = ic_timestamp.strftime("%Y-%m-%dT%H")

    config["forecast_path"] = f"{raw_inference}/{folder_structure}"
    config["output_path"] = f"{output_path}/{folder_structure}"

    if model_name == "nested-global":
        config["anemoi_reference_dataset_kwargs"] = {
            "cutout": [
                {
                    "dataset": f"{initial_conditions}/{folder_structure}/hrrr.zarr",
                    "trim_edge": trim_edge,
                },
                {
                    "dataset": f"{initial_conditions}/{folder_structure}/gfs.zarr",
                },
            ],
            "adjust": "all",
            "min_distance_km": min_distance_km,
        }

    updated_yaml_path = f"config/{model_name}.yaml"
    os.makedirs("config", exist_ok=True)
    with open(updated_yaml_path, "w") as conf:
        yaml.dump(config, conf)

    return updated_yaml_path


def run(
    output_path,
    initial_conditions,
    raw_inference,
    stac_path,
    version,
    ic_timestamp,
):
    """
    Process one forecast cycle into final domain-specific outputs and STAC.

    Output layout under the versioned storage prefix:
      version/data/raw/{YYYY}/{MM}/{DD}/{HH}/...
      version/data/postprocessed/{YYYY}/{MM}/{DD}/{HH}/nested-global.{YYYY-MM-DDTHH}.{LEAD_TIME}h.nc
      version/data/postprocessed/{YYYY}/{MM}/{DD}/{HH}/nested-lam.{YYYY-MM-DDTHH}.{LEAD_TIME}h.nc
      version/stac/items/{YYYY}/{MM}/{DD}/{HH}/nested-eagle-global-{YYYYMMDD-HH}z.json
      version/stac/items/{YYYY}/{MM}/{DD}/{HH}/nested-eagle-conus-{YYYYMMDD-HH}z.json
    """
    # prep configs
    lam_config = prep_config(
        model_name="nested-lam",
        ic_timestamp=ic_timestamp,
        output_path=output_path,
        initial_conditions=initial_conditions,
        raw_inference=raw_inference,
    )

    global_config = prep_config(
        model_name="nested-global",
        ic_timestamp=ic_timestamp,
        output_path=output_path,
        initial_conditions=initial_conditions,
        raw_inference=raw_inference,
    )

    # run postprocessing
    prewxvx.main(lam_config)

    prewxvx.main(global_config)

    # Write STAC items into the mounted output path (synced by AML datastore I/O).
    stac_item.write_stac_items(
        ic_timestamp=ic_timestamp,
        version=version,
        stac_path=stac_path,
        output_storage_url=OUTPUT_STORAGE_URL,
    )

    # Ingest each domain item into its target GeoCatalog collection.
    pc_ingest.ingest_stac_items(
        ic_timestamp=ic_timestamp,
        version=version,
        geocatalog_url=GEOCATALOG_URL,
        global_collection_id=GLOBAL_COLLECTION_ID,
        conus_collection_id=CONUS_COLLECTION_ID,
        output_storage_url=OUTPUT_STORAGE_URL,
    )

    return


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output_dir", type=str, required=True)
    parser.add_argument("--stac_items", type=str, required=True)
    parser.add_argument("--initial_conditions", type=str, required=True)
    parser.add_argument("--raw_inference", type=str, required=True)
    parser.add_argument("--run_context", required=False)
    args = parser.parse_args()

    ic_timestamp = utils.resolve_ic_timestamp(args.run_context)

    output_path = args.output_dir
    initial_conditions = args.initial_conditions
    raw_inference = args.raw_inference
    stac_path = args.stac_items

    run(
        output_path=output_path,
        initial_conditions=initial_conditions,
        raw_inference=raw_inference,
        stac_path=stac_path,
        ic_timestamp=ic_timestamp,
        version=VERSION,
    )
