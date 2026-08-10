"""Run Nested-EAGLE inference for a single resolved forecast cycle."""

import argparse
import os

import utils
import yaml
from config import FREQ, LEAD_TIME, MIN_DISTANCE_KM, TRIM_EDGE
from eagle.tools.inference import main as eagle_inference


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
    """Build the inference YAML config for one cycle and return its path."""
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
    ic_timestamp,
):
    """Execute model inference using the generated cycle-specific config."""
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
    parser.add_argument("--run_context", required=False)
    args = parser.parse_args()

    ic_timestamp = utils.resolve_ic_timestamp(args.run_context)

    input_path = args.input_dir
    output_path = args.output_dir
    checkpoint_path = args.checkpoint

    run(
        lead_time=LEAD_TIME,
        checkpoint_path=checkpoint_path,
        input_path=input_path,
        output_path=output_path,
        ic_timestamp=ic_timestamp,
    )
