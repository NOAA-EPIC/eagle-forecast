"""
Local test client for the async Nested-EAGLE endpoint.

Usage:
    # Set these from `az ml online-endpoint show ...`
    export SCORING_URI="https://nested-eagle-async.<region>.inference.ml.azure.com/score"
    export SCORING_KEY="<primary key>"

    # Health check
    python test_client.py ping

    # Submit a forecast (returns job_id immediately, ~1s)
    python test_client.py submit \
        --gfs   "az://intialconditions/gfs/2026-05-13T00.zarr" \
        --hrrr  "az://intialconditions/hrrr/2026-05-13T00.zarr" \
        --ic    "2026-05-13T00" \
        --lead  240

    # Poll status until the forecast finishes
    python test_client.py poll --job-id a1b2c3d4e5f6

    # Submit and auto-poll until done
    python test_client.py run \
        --gfs   "az://..." \
        --hrrr  "az://..." \
        --ic    "2026-05-13T00"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request


def _post(body: dict) -> dict:
    uri = os.environ["SCORING_URI"]
    key = os.environ["SCORING_KEY"]
    req = urllib.request.Request(
        uri,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def cmd_ping(_args):
    print(json.dumps(_post({"action": "ping"}), indent=2))


def cmd_submit(args):
    body = {
        "action": "submit",
        "gfs_zarr_path":  args.gfs,
        "hrrr_zarr_path": args.hrrr,
        "ic_timestamp":   args.ic,
        "lead_time":      args.lead,
        "upload_results": args.upload,
    }
    resp = _post(body)
    print(json.dumps(resp, indent=2))


def cmd_poll(args):
    last_status = ""
    start = time.time()
    while True:
        resp = _post({"action": "status", "job_id": args.job_id})
        status = resp.get("status", "?")
        elapsed = int(time.time() - start)
        if status != last_status:
            print(f"[{elapsed:>4}s] status={status}")
            last_status = status
        if status in ("completed", "failed", "not_found"):
            print(json.dumps(resp, indent=2))
            sys.exit(0 if status == "completed" else 1)
        time.sleep(args.interval)


def cmd_run(args):
    sub_resp = _post({
        "action": "submit",
        "gfs_zarr_path":  args.gfs,
        "hrrr_zarr_path": args.hrrr,
        "ic_timestamp":   args.ic,
        "lead_time":      args.lead,
        "upload_results": args.upload,
    })
    print(json.dumps(sub_resp, indent=2))
    job_id = sub_resp.get("job_id")
    if not job_id:
        sys.exit("submit did not return a job_id; aborting")
    args.job_id = job_id
    cmd_poll(args)


def main() -> None:
    if not os.environ.get("SCORING_URI") or not os.environ.get("SCORING_KEY"):
        sys.exit("Set SCORING_URI and SCORING_KEY env vars first (see top of file)")

    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("ping").set_defaults(func=cmd_ping)

    p_sub = sub.add_parser("submit")
    p_sub.add_argument("--gfs",  required=True)
    p_sub.add_argument("--hrrr", required=True)
    p_sub.add_argument("--ic",   required=True, help="ic_timestamp, ISO8601 hourly e.g. 2026-05-13T00")
    p_sub.add_argument("--lead", type=int, default=240)
    p_sub.add_argument("--upload", action="store_true")
    p_sub.set_defaults(func=cmd_submit)

    p_poll = sub.add_parser("poll")
    p_poll.add_argument("--job-id", required=True)
    p_poll.add_argument("--interval", type=int, default=30)
    p_poll.set_defaults(func=cmd_poll)

    p_run = sub.add_parser("run")
    p_run.add_argument("--gfs",  required=True)
    p_run.add_argument("--hrrr", required=True)
    p_run.add_argument("--ic",   required=True)
    p_run.add_argument("--lead", type=int, default=240)
    p_run.add_argument("--upload", action="store_true")
    p_run.add_argument("--interval", type=int, default=30)
    p_run.set_defaults(func=cmd_run)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
