"""Resolve the cycle timestamp shared by all AML pipeline steps."""

import argparse
import json

import pandas as pd


def main():
    """Write a run-context JSON file containing the selected NRT timestamp."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--cycle_time_override",
        required=False,
        default=None,
        help="Optional ISO timestamp for manual/test runs, e.g. 2026-06-11T12:00:00Z",
    )
    args = parser.parse_args()

    if args.cycle_time_override:
        # Useful for reruns/backfills of a specific cycle.
        now = pd.Timestamp(args.cycle_time_override).floor("6h")
    else:
        # Use the previous completed 6-hour cycle for operational NRT runs.
        now = pd.Timestamp.now(tz="UTC").floor("6h") - pd.Timedelta("6h")

    payload = {
        "nrt_timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    with open(args.output, "w") as f:
        json.dump(payload, f, indent=2)

    print(f"Resolved time utc={payload['nrt_timestamp']}")


if __name__ == "__main__":
    main()
