import pandas as pd
import yaml


def get_nrt_timestamp(
    nrt_latency="6h",
):
    # first set to floor of 6 hours, as initialization are only on 6 hr windwos
    # then go back one initialization (6hr) for intended latency
    ic_timestamp = pd.Timestamp.now(tz="UTC").floor("6h") - pd.Timedelta(nrt_latency)

    return ic_timestamp


def load_config(
    path,
):
    with open(path, "r") as f:
        return yaml.safe_load(f)
