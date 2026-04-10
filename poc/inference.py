import argparse
import os
import yaml
from eagle.tools.inference import main as eagle_inference

import utils

from config import TRIM_EDGE, MIN_DISTANCE_KM, FREQ, LEAD_TIME


def prep_config(
    ic_timestamp,
    lead_time,
    checkpoint_path,
    input_path,
    output_path,
    trim_edge=TRIM_EDGE,
    min_distance_km=MIN_DISTANCE_KM,
    freq=FREQ,
):
    init_str = ic_timestamp.strftime("%Y-%m-%dT%H")

    folder_structure = ic_timestamp.strftime("%Y/%m/%d/%H")

    config = {
        "checkpoint_path": checkpoint_path,
        "lead_time": lead_time,
        "start_date": init_str,
        "end_date": init_str,
        "freq": freq,
        "input_dataset_kwargs": {
            "cutout": [
                {
                    "dataset": f"{input_path}/{folder_structure}/hrrr.zarr",
                    "trim_edge": trim_edge,
                },
                {
                    "dataset": f"{input_path}/{folder_structure}/gfs.zarr",
                },
            ],
            "adjust": "all",
            "min_distance_km": min_distance_km,
        },
        "output_path": f"{output_path}/{folder_structure}",
    }

    config_path = "config/inference.yaml"
    os.makedirs("config", exist_ok=True)
    with open(config_path, "w") as conf:
        yaml.dump(config, conf)

    return config_path


def run(
    lead_time,
    checkpoint_path,
    input_path,
    output_path,
):
    ic_timestamp = utils.get_nrt_timestamp()

    config_path = prep_config(
        ic_timestamp=ic_timestamp,
        lead_time=lead_time,
        checkpoint_path=checkpoint_path,
        input_path=input_path,
        output_path=output_path,
    )

    eagle_inference(config_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output_dir", type=str, required=True)
    parser.add_argument("--input_dir", type=str, required=True)
    parser.add_argument("--checkpoint", type=str, required=True)

    args = parser.parse_args()
    input_path = args.input_dir
    output_path = args.output_dir
    checkpoint_path = args.checkpoint

    run(
        lead_time=LEAD_TIME,
        checkpoint_path=checkpoint_path,
        input_path=input_path,
        output_path=output_path,
    )
