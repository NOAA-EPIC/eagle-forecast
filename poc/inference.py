import argparse
import os
import sys
from eagle.tools.inference import main as eagle_inference

import utils


def prep_config(
    ic_timestamp,
    lead_time,
    version,
    checkpoint_path,
):
    init_str = ic_timestamp.strftime("%Y-%m-%dT%H")

    config = {
        "checkpoint_path": f"{checkpoint_path}/inference-last.ckpt",
        "lead_time": lead_time,
        "start_date": init_str,
        "end_date": init_str,
        "freq": "6h",
        "input_dataset_kwargs": {
            "cutout": [
                {
                    "dataset": f"{version}/initial_conditions/{ic_timestamp.strftime('%Y/%m/%d/%H')}/hrrr.zarr",
                    "trim_edge": [25, 24, 25, 26],
                },
                {
                    "dataset": f"{version}/initial_conditions/{ic_timestamp.strftime('%Y/%m/%d/%H')}/gfs.zarr",
                },
            ],
            "adjust": "all",
            "min_distance_km": 6,
        },
        "output_path": f"{version}/inference/{ic_timestamp.strftime('%Y/%m/%d/%H')}",
    }

    return config


def run(
    version,
    lead_time,
    checkpoint_path,
):
    ic_timestamp = utils.get_nrt_timestamp()

    os.makedirs(
        f"{version}/inference/{ic_timestamp.strftime('%Y/%m/%d/%H')}", exist_ok=True
    )

    config = prep_config(
        version=version,
        ic_timestamp=ic_timestamp,
        lead_time=lead_time,
        checkpoint_path=checkpoint_path,
    )

    eagle_inference(config)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config")
    args = parser.parse_args()

    if not args.config:
        print("Example usage:  python inference.py --config config.yaml")
        sys.exit(1)

    config = utils.load_config(args.config)

    lead_time = config["lead_time"]
    version = config["version"]
    checkpoint_path = config["checkpoint_path"]

    run(version=version, lead_time=lead_time, checkpoint_path=checkpoint_path)
