"""Shared utility helpers for cycle-time and YAML config handling."""

import json

import pandas as pd
import yaml

# Optional override for manual/historical runs when no run_context is provided.
# Examples:
#   MANUAL_IC_TIMESTAMP = "2026-07-28T06:00:00Z"
#   MANUAL_IC_TIMESTAMP = "2026-07-28 06:00:00+00:00"
MANUAL_IC_TIMESTAMP = None


def _normalize_cycle_timestamp(value) -> pd.Timestamp:
    """
    Convert an input timestamp to a UTC 6-hour cycle boundary.

    Args:
        value: Any pandas-compatible timestamp input.

    Returns:
        pd.Timestamp: UTC timestamp floored to the nearest 6-hour boundary.
    """
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.floor("6h")


def get_nrt_timestamp():
    """
    Return the forecast cycle timestamp for non-scheduled/manual runs.

    Priority:
      1. `MANUAL_IC_TIMESTAMP` when set (for historical reruns/backfills)
      2. Previous available 6-hour UTC cycle
    """
    if MANUAL_IC_TIMESTAMP:
        return _normalize_cycle_timestamp(MANUAL_IC_TIMESTAMP)

    ic_timestamp = pd.Timestamp.now(tz="UTC").floor("6h") - pd.Timedelta("6h")
    return ic_timestamp


def load_config(path):
    """Load and parse a YAML file into a Python dictionary."""
    with open(path, "r") as f:
        return yaml.safe_load(f)


def resolve_ic_timestamp(run_context_path: str | None):
    """
    Resolve the initialization cycle timestamp for a pipeline step.

    Args:
        run_context_path: Path to the run-context JSON file produced by
            `resolve_init_time.py`. If missing/None, fallback behavior from
            `get_nrt_timestamp()` is used.

    Returns:
        pd.Timestamp: UTC cycle timestamp used by the step.
    """
    if run_context_path:
        with open(run_context_path, "r", encoding="utf-8") as f:
            run_context = json.load(f)
        return _normalize_cycle_timestamp(run_context["nrt_timestamp"])

    return get_nrt_timestamp()
