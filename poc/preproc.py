"""Prepare GFS/HRRR initial-condition Zarr inputs for one forecast cycle."""

import argparse
import os

import pandas as pd
import utils
import yaml
from config import LEAD_TIME, MULTISTEP_INPUT
from ufs2arco.driver import Driver


def create_yaml(
    model_name,
    init,
    end,
    output_path,
    ic_timestamp,
):
    """Render a cycle-specific ufs2arco config and return its file path."""
    config = utils.load_config(f"config/{model_name}.yaml")

    folder_structure = ic_timestamp.strftime("%Y/%m/%d/%H")

    config["source"]["t0"]["start"] = init.strftime("%Y-%m-%dT%H")
    config["source"]["t0"]["end"] = end.strftime("%Y-%m-%dT%H")

    config["directories"]["zarr"] = (
        f"{output_path}/{folder_structure}/{model_name}.zarr"
    )
    config["directories"]["cache"] = f"cache/{model_name}"
    config["directories"]["logs"] = f"{output_path}/{folder_structure}/logs"

    updated_yaml_path = f"{output_path}/{folder_structure}/config/{model_name}.yaml"
    os.makedirs(f"{output_path}/{folder_structure}/config", exist_ok=True)
    with open(updated_yaml_path, "w") as conf:
        yaml.dump(config, conf)

    return updated_yaml_path


def prep_configs(
    ic_timestamp,
    lead_time,
    multistep_input,
    output_path,
):
    """Build GFS and HRRR ufs2arco config files for the selected cycle."""
    if multistep_input:
        init = ic_timestamp - pd.Timedelta("6h")
    else:
        init = ic_timestamp

    end = ic_timestamp + pd.Timedelta(f"{lead_time}h")

    gfs_yaml = create_yaml(
        model_name="gfs",
        init=init,
        end=end,
        output_path=output_path,
        ic_timestamp=ic_timestamp,
    )

    hrrr_yaml = create_yaml(
        model_name="hrrr",
        init=init,
        end=end,
        output_path=output_path,
        ic_timestamp=ic_timestamp,
    )

    return [gfs_yaml, hrrr_yaml]


def load_initial_conditions(
    configs,
):
    """Execute ufs2arco data movers for GFS and HRRR config files."""
    print("Loading GFS")
    Driver(configs[0]).run()

    print("Loading HRRR")
    Driver(configs[1]).run()


def run(lead_time, multistep_input, output_path, ic_timestamp):
    """Run preprocessing for a fixed NRT cycle timestamp."""
    print(f"Loading initial conditions for {ic_timestamp}")

    configs = prep_configs(
        ic_timestamp=ic_timestamp,
        lead_time=lead_time,
        multistep_input=multistep_input,
        output_path=output_path,
    )

    load_initial_conditions(
        configs=configs,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output_dir", type=str, required=True)
    parser.add_argument("--run_context", required=False)
    args = parser.parse_args()

    ic_timestamp = utils.resolve_ic_timestamp(args.run_context)

    output_path = args.output_dir

    run(
        lead_time=LEAD_TIME,
        multistep_input=MULTISTEP_INPUT,
        output_path=output_path,
        ic_timestamp=ic_timestamp,
    )
