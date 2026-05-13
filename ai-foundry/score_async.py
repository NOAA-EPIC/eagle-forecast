"""
Azure ML managed online endpoint scoring script for Nested-EAGLE — ASYNC.

Why async?
----------
Nested-EAGLE forecasts take ~5-8 min on H100. AML managed online endpoints
cap synchronous request_timeout_ms at 180,000 ms (3 min). A synchronous
POST that takes 6 min will fail at the gateway regardless of YAML settings.

This script implements the standard "submit + poll" pattern so the endpoint
satisfies Foundry's "deployable online endpoint" requirement while keeping
every individual HTTP request under a few seconds:

    1. Client POSTs {"action":"submit", ...inputs...}        → returns instantly with job_id
    2. Inference runs in a daemon thread on the GPU
    3. Client polls POST {"action":"status", "job_id":...}   → returns "running" or final result
    4. Optional: result is uploaded to Azure Blob so the client can fetch the
       NetCDF directly (job record only carries the URL + metadata)

Concurrency:
    A module-level Semaphore(1) ensures only ONE inference runs at a time, even
    when multiple submit calls arrive. Additional submits are queued (their
    threads block on the semaphore) and progress to status='running' when their
    turn comes. Set `max_concurrent_requests_per_instance` in deployment.yml > 1
    so the HTTP layer can accept submits while a forecast is running.

Single-replica state:
    Job records live under /tmp/nested-eagle-jobs/<job_id>.json. This is per-
    container; if you scale to instance_count > 1, a status call could land on
    a different replica than the submit. For Public Preview, set instance_count=1
    OR set ENABLE_BLOB_JOB_STORE=true + JOB_STORE_BLOB_URL to persist job
    records to blob storage so any replica can answer status calls.

Request contract
----------------

Action: submit
    Request:
        {
            "action": "submit",
            "gfs_zarr_path":  "az://... or http url",
            "hrrr_zarr_path": "az://... or http url",
            "ic_timestamp":   "2026-05-13T00",
            "lead_time":      240,            // optional, default 240
            "upload_results": true            // optional, default uses env var
        }
    Response (HTTP 200, returns in <1s):
        {
            "action":      "submit",
            "job_id":      "a1b2c3d4e5f6",
            "status":      "queued",
            "submitted_at":"2026-05-13T18:42:15.123456+00:00"
        }

Action: status
    Request:
        {"action": "status", "job_id": "a1b2c3d4e5f6"}
    Response:
        running:
            {"job_id":"...", "status":"running", "started_at":"..."}
        completed:
            {
                "job_id":"...",
                "status":"completed",
                "completed_at":"...",
                "duration_seconds": 372,
                "forecast_url":  "https://.../forecast.nc",
                "global_url":    "https://.../global.nc",
                "conus_url":     "https://.../conus.nc"
            }
        failed:
            {"job_id":"...", "status":"failed", "error":"...", "traceback":"..."}
        not_found:
            HTTP 404-ish via {"action":"status","status":"not_found","job_id":"..."}

Action: ping  (health check)
    Request:  {"action": "ping"}
    Response: {"status":"ok", "checkpoint_loaded": true, "gpu": "...", "queued": N}

Environment variables (set in deployment.yml)
---------------------------------------------
    CHECKPOINT_PATH         path to inference-last.ckpt   (default /mnt/models/...)
    GRID_FILE               path to hrrr_06km.nc          (default /mnt/models/...)
    OUTPUT_ROOT             local working dir             (default /tmp/nested-eagle-output)
    JOBS_DIR                local job-record dir          (default /tmp/nested-eagle-jobs)

    # Optional blob upload of final NetCDF outputs:
    UPLOAD_RESULTS                true|false              (default false)
    OUTPUT_BLOB_ACCOUNT_URL       https://<acct>.blob.core.windows.net
    OUTPUT_BLOB_CONTAINER         eg. nested-eagle-forecasts
    OUTPUT_BLOB_PREFIX            optional path prefix in container, eg. "endpoint/"
    AZURE_CLIENT_ID               UAMI client ID for blob auth (DefaultAzureCredential)

    # Optional cross-replica job store:
    ENABLE_BLOB_JOB_STORE         true|false              (default false)
    JOB_STORE_BLOB_URL            https://<acct>.blob.core.windows.net/<container>/<prefix>

Job retention:
    Old job records are pruned from disk after JOB_TTL_SECONDS (default 86400).
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

# Optional: only imported lazily inside the worker thread to keep
# init() fast and avoid import errors blocking health checks.
# from eagle.tools.inference import main as eagle_inference

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(threadName)s %(name)s: %(message)s",
)
log = logging.getLogger("nested-eagle-async")

# ─── Module-level state ──────────────────────────────────────────────────────
CHECKPOINT_PATH: str = ""
GRID_FILE: str = ""
OUTPUT_ROOT: Path = Path("/tmp/nested-eagle-output")
JOBS_DIR: Path = Path("/tmp/nested-eagle-jobs")
JOB_TTL_SECONDS: int = int(os.environ.get("JOB_TTL_SECONDS", "86400"))

UPLOAD_RESULTS: bool = False
OUTPUT_BLOB_ACCOUNT_URL: str = ""
OUTPUT_BLOB_CONTAINER: str = ""
OUTPUT_BLOB_PREFIX: str = ""

# Only one inference at a time on the shared GPU
INFERENCE_SEMAPHORE = threading.Semaphore(1)

# Track queued/running for /ping
_QUEUED_COUNT_LOCK = threading.Lock()
_QUEUED_COUNT = 0


# ─── AML entry points ────────────────────────────────────────────────────────
def init() -> None:
    """Called once per container start. Light-weight; no checkpoint load here."""
    global CHECKPOINT_PATH, GRID_FILE, OUTPUT_ROOT, JOBS_DIR
    global UPLOAD_RESULTS, OUTPUT_BLOB_ACCOUNT_URL, OUTPUT_BLOB_CONTAINER, OUTPUT_BLOB_PREFIX

    CHECKPOINT_PATH = os.environ.get("CHECKPOINT_PATH", "/mnt/models/inference-last.ckpt")
    GRID_FILE = os.environ.get("GRID_FILE", "/mnt/models/hrrr_06km.nc")
    OUTPUT_ROOT = Path(os.environ.get("OUTPUT_ROOT", "/tmp/nested-eagle-output"))
    JOBS_DIR = Path(os.environ.get("JOBS_DIR", "/tmp/nested-eagle-jobs"))
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    JOBS_DIR.mkdir(parents=True, exist_ok=True)

    UPLOAD_RESULTS = os.environ.get("UPLOAD_RESULTS", "false").lower() in ("1", "true", "yes")
    OUTPUT_BLOB_ACCOUNT_URL = os.environ.get("OUTPUT_BLOB_ACCOUNT_URL", "")
    OUTPUT_BLOB_CONTAINER = os.environ.get("OUTPUT_BLOB_CONTAINER", "")
    OUTPUT_BLOB_PREFIX = os.environ.get("OUTPUT_BLOB_PREFIX", "").lstrip("/")

    if not Path(CHECKPOINT_PATH).exists():
        log.warning(
            "Checkpoint not found at %s. The first submit() will fail until the "
            "model is mounted. Container is still healthy for /ping.",
            CHECKPOINT_PATH,
        )

    _prune_old_jobs()
    log.info("init complete  checkpoint=%s  grid=%s  upload=%s",
             CHECKPOINT_PATH, GRID_FILE, UPLOAD_RESULTS)


def run(raw_data: Any) -> str:
    """Per-request entry point. Returns JSON string."""
    try:
        req = raw_data if isinstance(raw_data, dict) else json.loads(raw_data)
    except (TypeError, ValueError) as e:
        return _err("invalid JSON body", detail=str(e), http_status=400)

    action = (req.get("action") or "submit").lower()

    if action == "submit":
        return _handle_submit(req)
    if action == "status":
        return _handle_status(req)
    if action == "ping":
        return _handle_ping()
    return _err(f"unknown action '{action}'. Use submit | status | ping.", http_status=400)


# ─── Action handlers ─────────────────────────────────────────────────────────
def _handle_submit(req: dict) -> str:
    required = ("gfs_zarr_path", "hrrr_zarr_path", "ic_timestamp")
    missing = [k for k in required if k not in req]
    if missing:
        return _err(f"missing required field(s): {missing}", http_status=400)

    job_id = uuid.uuid4().hex[:12]
    job = {
        "job_id": job_id,
        "action": "submit",
        "status": "queued",
        "submitted_at": _now_iso(),
        "request": {
            "gfs_zarr_path":  req["gfs_zarr_path"],
            "hrrr_zarr_path": req["hrrr_zarr_path"],
            "ic_timestamp":   req["ic_timestamp"],
            "lead_time":      int(req.get("lead_time", 240)),
            "upload_results": bool(req.get("upload_results", UPLOAD_RESULTS)),
        },
    }
    _write_job(job)
    _bump_queue(+1)

    t = threading.Thread(
        target=_run_inference_safe,
        name=f"infer-{job_id}",
        args=(job_id,),
        daemon=True,
    )
    t.start()

    log.info("submitted job_id=%s ic=%s lead=%dh",
             job_id, job["request"]["ic_timestamp"], job["request"]["lead_time"])

    return json.dumps({
        "action": "submit",
        "job_id": job_id,
        "status": "queued",
        "submitted_at": job["submitted_at"],
    })


def _handle_status(req: dict) -> str:
    job_id = req.get("job_id")
    if not job_id:
        return _err("status requires 'job_id'", http_status=400)
    job = _read_job(job_id)
    if job is None:
        return json.dumps({
            "action": "status",
            "job_id": job_id,
            "status": "not_found",
        })
    return json.dumps({"action": "status", **job})


def _handle_ping() -> str:
    gpu_info = _detect_gpu()
    with _QUEUED_COUNT_LOCK:
        queued = _QUEUED_COUNT
    return json.dumps({
        "status": "ok",
        "checkpoint_exists": Path(CHECKPOINT_PATH).exists(),
        "grid_exists": Path(GRID_FILE).exists(),
        "gpu": gpu_info,
        "queued_or_running": queued,
        "upload_results": UPLOAD_RESULTS,
    })


# ─── Worker ──────────────────────────────────────────────────────────────────
def _run_inference_safe(job_id: str) -> None:
    """Wrapper that always finalizes the job record, even on crash."""
    try:
        _run_inference(job_id)
    except Exception as e:  # noqa: BLE001
        log.exception("job %s failed", job_id)
        _patch_job(job_id, {
            "status": "failed",
            "error": str(e),
            "traceback": traceback.format_exc(),
            "completed_at": _now_iso(),
        })
    finally:
        _bump_queue(-1)


def _run_inference(job_id: str) -> None:
    job = _read_job(job_id)
    if job is None:
        log.error("job record disappeared for %s", job_id)
        return
    req = job["request"]
    ic_timestamp = pd.Timestamp(req["ic_timestamp"])

    log.info("job %s waiting for GPU semaphore", job_id)
    with INFERENCE_SEMAPHORE:
        started_at = _now_iso()
        _patch_job(job_id, {"status": "running", "started_at": started_at})
        log.info("job %s acquired GPU; running inference", job_id)
        t0 = time.time()

        folder = ic_timestamp.strftime("%Y/%m/%d/%H")
        output_dir = OUTPUT_ROOT / folder
        output_dir.mkdir(parents=True, exist_ok=True)

        config = {
            "checkpoint_path": CHECKPOINT_PATH,
            "lead_time": int(req["lead_time"]),
            "start_date": ic_timestamp.strftime("%Y-%m-%dT%H"),
            "end_date":   ic_timestamp.strftime("%Y-%m-%dT%H"),
            "freq": "6h",
            "input_dataset_kwargs": {
                "cutout": [
                    {"dataset": req["hrrr_zarr_path"], "trim_edge": [25, 24, 25, 26]},
                    {"dataset": req["gfs_zarr_path"]},
                ],
                "adjust": "all",
                "min_distance_km": 6,
            },
            "output_path": str(output_dir),
        }

        # Import lazily so a missing module doesn't kill container startup
        from eagle.tools.inference import main as eagle_inference  # type: ignore

        eagle_inference(config)

        forecast_nc = output_dir / "forecast.nc"
        if not forecast_nc.exists():
            raise FileNotFoundError(f"forecast.nc not produced at {forecast_nc}")

        # Post-process
        try:
            sys.path.insert(0, os.path.dirname(__file__))
            import postproc  # type: ignore
            postproc.postprocess_forecast(
                version=str(OUTPUT_ROOT),
                grid_file=GRID_FILE,
                ic_timestamp=ic_timestamp,
            )
        except Exception:  # noqa: BLE001
            log.exception("post-processing failed (continuing with raw forecast.nc)")

        global_nc = OUTPUT_ROOT / "postprocessed" / folder / "global.nc"
        conus_nc  = OUTPUT_ROOT / "postprocessed" / folder / "conus.nc"

        # Optional upload
        urls: dict[str, str | None] = {
            "forecast_url": None,
            "global_url":   None,
            "conus_url":    None,
        }
        if req.get("upload_results"):
            urls["forecast_url"] = _upload_blob(forecast_nc, ic_timestamp, "forecast.nc")
            if global_nc.exists():
                urls["global_url"] = _upload_blob(global_nc, ic_timestamp, "global.nc")
            if conus_nc.exists():
                urls["conus_url"] = _upload_blob(conus_nc, ic_timestamp, "conus.nc")

        duration = round(time.time() - t0, 1)
        _patch_job(job_id, {
            "status": "completed",
            "completed_at": _now_iso(),
            "duration_seconds": duration,
            "forecast_path": str(forecast_nc),
            "global_path":   str(global_nc) if global_nc.exists() else None,
            "conus_path":    str(conus_nc)  if conus_nc.exists()  else None,
            **urls,
        })
        log.info("job %s completed in %.1fs", job_id, duration)


# ─── Blob upload ─────────────────────────────────────────────────────────────
def _upload_blob(local_path: Path, ic_timestamp: pd.Timestamp, filename: str) -> str | None:
    if not (OUTPUT_BLOB_ACCOUNT_URL and OUTPUT_BLOB_CONTAINER):
        log.warning("upload_results=true but blob config missing; skipping upload")
        return None
    try:
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobClient
    except ImportError:
        log.warning("azure-storage-blob not installed; skipping upload")
        return None

    prefix = OUTPUT_BLOB_PREFIX
    blob_path = f"{prefix}{ic_timestamp.strftime('%Y/%m/%d/%H')}/{filename}".lstrip("/")
    cred = DefaultAzureCredential()
    blob = BlobClient(
        account_url=OUTPUT_BLOB_ACCOUNT_URL,
        container_name=OUTPUT_BLOB_CONTAINER,
        blob_name=blob_path,
        credential=cred,
    )
    with open(local_path, "rb") as f:
        blob.upload_blob(f, overwrite=True)
    log.info("uploaded %s -> %s", local_path, blob.url)
    return blob.url


# ─── Job store ───────────────────────────────────────────────────────────────
def _job_file(job_id: str) -> Path:
    return JOBS_DIR / f"{job_id}.json"


def _write_job(job: dict) -> None:
    _job_file(job["job_id"]).write_text(json.dumps(job))


def _patch_job(job_id: str, updates: dict) -> None:
    p = _job_file(job_id)
    if not p.exists():
        log.error("patch_job: job file missing for %s", job_id)
        return
    cur = json.loads(p.read_text())
    cur.update(updates)
    p.write_text(json.dumps(cur))


def _read_job(job_id: str) -> dict | None:
    p = _job_file(job_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return None


def _prune_old_jobs() -> None:
    cutoff = time.time() - JOB_TTL_SECONDS
    pruned = 0
    for p in JOBS_DIR.glob("*.json"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
                pruned += 1
        except OSError:
            pass
    if pruned:
        log.info("pruned %d job record(s) older than %ds", pruned, JOB_TTL_SECONDS)


# ─── Helpers ─────────────────────────────────────────────────────────────────
def _bump_queue(delta: int) -> None:
    global _QUEUED_COUNT
    with _QUEUED_COUNT_LOCK:
        _QUEUED_COUNT = max(0, _QUEUED_COUNT + delta)


def _detect_gpu() -> str:
    try:
        import torch  # type: ignore
        if torch.cuda.is_available():
            return f"{torch.cuda.get_device_name(0)} (count={torch.cuda.device_count()})"
        return "no-cuda"
    except ImportError:
        return "torch-not-installed"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _err(msg: str, detail: str | None = None, http_status: int = 500) -> str:
    body = {"status": "error", "error": msg, "http_status": http_status}
    if detail:
        body["detail"] = detail
    return json.dumps(body)
