# Async (submit/poll) deployment for Nested-EAGLE

This package adds a Foundry-compatible **managed online endpoint** on top of the
existing BYOC container. Inference takes 5-8 minutes, which is longer than AML's
3-minute HTTP gateway timeout — so the endpoint exposes a **submit / status**
contract instead of synchronous inference.

```
client ─POST {"action":"submit", ...}─▶ score_async.py.run()
                                          │
                                          ├─ writes /tmp/jobs/<id>.json (status=queued)
                                          ├─ spawns daemon thread
                                          └─ returns job_id in <1 sec
                                            
[worker thread acquires Semaphore(1), runs 6-min inference, writes result]
                                            
client ─POST {"action":"status", "job_id":...}─▶ returns "running" or final result
```

## Files

| File | Purpose |
|---|---|
| `score_async.py`  | New scoring script. Use this **instead of** `score.py` for the online endpoint. |
| `score.py`        | Original synchronous script — kept for the pipeline (where 6 min is fine) and reference. |
| `endpoint.yml`    | Managed online endpoint definition. |
| `deployment.yml`  | Deployment definition (references `score_async.py`, `nested-eagle-inference:10`, `nested-eagle:2`). |
| `test_client.py`  | CLI client for `ping`, `submit`, `poll`, and `run` (submit + auto-poll). |
| `conda.yaml`, `Dockerfile` | Unchanged — same environment Mariah already built (`nested-eagle-inference:10`). |

## Prerequisites

1. The managed identity used by AML compute has these roles (see RBAC email):
   - **GeoCatalog Reader** (already done)
   - **GeoCatalog Ingestion Manager** (needed by the pipeline, not the endpoint)
   - **Storage Blob Data Reader** on `intialconditions`  *(if requests reference `az://` Zarr paths there)*
   - **Storage Blob Data Contributor** on `eagleforecasts`  *(only if `UPLOAD_RESULTS=true`)*
   - **AcrPull** on the workspace ACR

2. The model `nested-eagle:2` is registered in the workspace and contains both:
   - `inference-last.ckpt`
   - `hrrr_06km.nc`

3. The `nested-eagle-inference:10` environment is already built (Mariah did this).

4. GPU quota in the workspace's region for the chosen SKU (H100 or A100).

## Deploy

```bash
# 1. Create the endpoint (one-time; takes ~5 min)
az ml online-endpoint create \
  -f endpoint.yml \
  -g <resource-group> \
  -w <workspace>

# 2. Create the deployment (this is the slow step — ~15-25 min the first time
#    because AML provisions the GPU node and pulls the container image).
az ml online-deployment create \
  -f deployment.yml \
  -g <resource-group> \
  -w <workspace> \
  --all-traffic
```

## Test

```bash
# Capture endpoint URI + key
SCORING_URI=$(az ml online-endpoint show -n nested-eagle-async -g <rg> -w <ws> --query scoring_uri -o tsv)
SCORING_KEY=$(az ml online-endpoint get-credentials -n nested-eagle-async -g <rg> -w <ws> --query primaryKey -o tsv)

export SCORING_URI SCORING_KEY

# Health check (should return {"status":"ok", ...})
python test_client.py ping

# Submit a forecast and auto-poll until it finishes
python test_client.py run \
  --gfs   "az://intialconditions/gfs/2026-05-13T00.zarr" \
  --hrrr  "az://intialconditions/hrrr/2026-05-13T00.zarr" \
  --ic    "2026-05-13T00" \
  --lead  240
```

Expected timing per request:
- `ping`     ~50 ms
- `submit`   <1 sec  → returns `{"job_id":"...", "status":"queued"}`
- `status`   ~100 ms → returns `"queued"` → `"running"` → `"completed"` (or `"failed"`)
- Worker thread does the real 5-8 min inference between the first `running` and `completed`.

## Verifying the deployment

| Check | Command |
|---|---|
| Endpoint is healthy | `python test_client.py ping` → `"status":"ok", "checkpoint_exists": true` |
| Logs (worker thread, GPU init, errors) | `az ml online-deployment get-logs -n blue --endpoint-name nested-eagle-async -g <rg> -w <ws>` |
| GPU is actually attached | `ping` output shows e.g. `"gpu": "NVIDIA H100 80GB HBM3 (count=1)"` |
| Concurrent submits queue properly | Run two `submit`s back-to-back → second one's worker thread blocks on the semaphore; `ping` shows `queued_or_running: 2`. |

## What changed vs. the original `score.py`

| Concern | Original `score.py` | `score_async.py` |
|---|---|---|
| HTTP timeout | Holds the request for 5-8 min — **breaks Foundry's 3-min gateway** | Each call returns in <1 sec |
| Concurrency | First request blocks all others until done | New `submit` returns immediately; status calls are independent |
| GPU sharing | Implicit (only one request at a time anyway) | Explicit `Semaphore(1)` so only one inference runs even with multiple submits |
| Failures | Returned in the same blocking response | Returned via `status` after the worker thread captures the traceback |
| Result delivery | NetCDF paths on the container's `/tmp` (not reachable externally) | Optional upload to Azure Blob, URLs returned in status |

## Single-instance limitation (and how to lift it later)

Job state lives in `/tmp/nested-eagle-jobs/` on the specific container that
served the `submit`. With `instance_count: 1` (the default in `deployment.yml`)
this is fine. If you scale to multiple replicas later:

- Either pin status calls to the originating instance via APIM session affinity, **or**
- Implement the blob-backed job store (`ENABLE_BLOB_JOB_STORE=true`) so any
  replica can answer status calls.

For Public Preview submission to Foundry, **stay at instance_count=1** until
real production demand justifies horizontal scaling. The semaphore already
prevents the single GPU from being overloaded.

## Foundry model-card update

The model card in `foundry_registration/required_metadata.md` should describe
the async contract in field 17 (Sample API response). Suggested wording:

> Nested-EAGLE inference is long-running (~6 minutes for a 240h forecast). The
> endpoint exposes an asynchronous **submit / status** contract:
>
> 1. `POST /score` with `{"action":"submit", ...inputs...}` returns a job_id
>    immediately.
> 2. Poll `POST /score` with `{"action":"status", "job_id":"..."}` every 30
>    seconds until `status` is `completed` or `failed`.
> 3. The completed response returns blob URLs to `forecast.nc`, `global.nc`,
>    and `conus.nc`.

## Cost note

This deployment holds an H100 (or A100) 24/7. With `instance_count: 1` on
`Standard_NC40ads_H100_v5` in East US, that's roughly **$25-30k/month**.
If the goal is just to satisfy Foundry's "must have a deployable endpoint"
requirement and not to serve real production traffic, consider switching
`instance_type` to `Standard_NC24ads_A100_v4` (~$3-4k/month) — inference will
be slower (~10-12 min) but the async pattern makes that invisible to callers.
