import argparse
import os
import yaml
from eagle.tools.prewxvx import main as prewxvx

import utils
import stac_item
import pc_ingest

from config import (
    VERSION,
    TRIM_EDGE,
    MIN_DISTANCE_KM,
    OUTPUT_STORAGE_URL,
    GEOCATALOG_URL,
    COLLECTION_ID,
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
):
    """
    Final blob layout:
    version/data/raw/{YYYY}/{MM}/{DD}/{HH}/forecast.nc
    version/data/postprocessed/{YYYY}/{MM}/{DD}/{HH}/global.nc
    version/data/postprocessed/{YYYY}/{MM}/{DD}/{HH}/conus.nc
    version/stac/collection.json
    version/stac/items/{YYYY}/{MM}/{DD}/{HH}/postprocessed.json
    """
    ic_timestamp = utils.get_nrt_timestamp()

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
    prewxvx(lam_config)

    prewxvx(global_config)

    # create and upload stac items to blob store
    stac_item.write_stac_items(
        ic_timestamp=ic_timestamp,
        version=version,
        stac_path=stac_path,
        output_storage_url=OUTPUT_STORAGE_URL,
    )

    # ingest to pc
    pc_ingest.ingest_stac_items(
        ic_timestamp=ic_timestamp,
        version=version,
        geocatalog_url=GEOCATALOG_URL,
        collection_id=COLLECTION_ID,
        output_storage_url=OUTPUT_STORAGE_URL,
    )

    return


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output_dir", type=str, required=True)
    parser.add_argument("--stac_items", type=str, required=True)
    parser.add_argument("--initial_conditions", type=str, required=True)
    parser.add_argument("--raw_inference", type=str, required=True)

    args = parser.parse_args()

    output_path = args.output_dir
    initial_conditions = args.initial_conditions
    raw_inference = args.raw_inference
    stac_path = args.stac_items

    run(
        output_path=output_path,
        initial_conditions=initial_conditions,
        raw_inference=raw_inference,
        stac_path=stac_path,
        version=VERSION,
    )
