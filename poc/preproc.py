import pandas as pd
import argparse
import yaml
import os
import sys
from ufs2arco.driver import Driver

import utils


def create_yaml(
    yaml_name,
    ic_timestamp,
    init,
    end,
    version,
):
    config = utils.load_config(f"config/{yaml_name}.yaml")

    folder_structure = ic_timestamp.strftime("%Y/%m/%d/%H")

    config["source"]["t0"]["start"] = init.strftime("%Y-%m-%dT%H")
    config["source"]["t0"]["end"] = end.strftime("%Y-%m-%dT%H")
    config["directories"]["zarr"] = (
        f"{version}/initial_conditions/{folder_structure}/{yaml_name}.zarr"
    )
    config["directories"]["cache"] = (
        f"{version}/initial_conditions/{folder_structure}/cache"
    )
    config["directories"]["logs"] = (
        f"{version}/initial_conditions/{folder_structure}/logs"
    )

    updated_yaml_name = (
        f"{version}/initial_conditions/{folder_structure}/{yaml_name}.yaml"
    )

    os.makedirs(f"{version}/initial_conditions/{folder_structure}", exist_ok=True)
    with open(updated_yaml_name, "w") as conf:
        yaml.dump(config, conf)

    return updated_yaml_name


def prep_configs(
    ic_timestamp,
    lead_time,
    version,
    multistep_input,
):
    if multistep_input:
        init = ic_timestamp - pd.Timedelta("6h")
    else:
        init = ic_timestamp

    end = ic_timestamp + pd.Timedelta(f"{lead_time}h")

    if version == "nested_eagle":
        # create gfs yaml
        gfs_yaml = create_yaml(
            yaml_name="gfs",
            ic_timestamp=ic_timestamp,
            init=init,
            end=end,
            version=version,
        )

        # create hrrr yaml
        hrrr_yaml = create_yaml(
            yaml_name="hrrr",
            ic_timestamp=ic_timestamp,
            init=init,
            end=end,
            version=version,
        )

        return [gfs_yaml, hrrr_yaml]

    else:
        print("nested_eagle is the only model option right now")
        

def load_initial_conditions(
    configs,
    version,
):
    if version == "nested_eagle":
        Driver(configs[0]).run()  # gfs
        Driver(configs[1]).run()  # hrrr

    else:
        print("nested_eagle is the only model option right now")


def run(
    lead_time,
    version,
    multistep_input,
):
    ic_timestamp = utils.get_nrt_timestamp()

    configs = prep_configs(
        ic_timestamp=ic_timestamp,
        lead_time=lead_time,
        version=version,
        multistep_input=multistep_input,
    )

    load_initial_conditions(
        configs=configs,
        version=version,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config")
    args = parser.parse_args()

    if not args.config:
        print("Example usage:  python preproc.py --config config.yaml")
        sys.exit(1)

    config = utils.load_config(args.config)

    lead_time = config["lead_time"]
    version = config["version"]
    multistep_input = config["multistep_input"]

    run(
        lead_time=lead_time,
        version=version,
        multistep_input=multistep_input,
    )
