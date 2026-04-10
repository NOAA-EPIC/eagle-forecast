import pandas as pd
import yaml


def get_nrt_timestamp():
    # first set to floor of 6 hours, as initialization are only on 6 hr windwos
    ic_timestamp = pd.Timestamp.now(tz="UTC").floor("6h") - pd.Timedelta("6h")

    return ic_timestamp


def load_config(path):
    with open(path, "r") as f:
        return yaml.safe_load(f)
