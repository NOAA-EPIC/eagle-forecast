# Nested-EAGLE — Azure AI Foundry Online Endpoint

This directory packages Nested-EAGLE as an Azure ML managed online endpoint so the model can be onboarded to **Azure AI Foundry**. It contains both the container definition and two deployment patterns:

| Pattern | Script | When to use |
|---|---|---|
| **Async (submit/poll)** | `score_async.py` | **Default — required for Foundry.** Inference takes ~5-8 min, longer than AML's 180s gateway timeout. Submit/poll keeps every HTTP call under a second. |
| **Synchronous** | `score.py` | Original implementation. Keep for direct testing or pipeline reuse where the 3-min cap isn't a concern. |

## What's in this folder

```
ai-foundry/
├── Dockerfile          # CUDA 12.1 base + anemoi-inference + eagle-tools
├── conda.yaml          # Python dependencies
├── score.py            # Synchronous scoring script (original entry point)
├── score_async.py      # Async submit/poll scoring script — used by deployment.yml
├── endpoint.yml        # Managed online endpoint definition (auth_mode: key)
├── deployment.yml      # Deployment referencing score_async.py + nested-eagle-inference:10 + nested-eagle:2
├── test_client.py      # CLI: ping / submit / poll / run
├── README.md           # This file
└── README_async.md     # Deep-dive on the async pattern: contract, concurrency, blob upload, model-card wording
```

The scripts pull two helpers from `poc/` at deploy time:
- `postproc.py` — splits raw forecast into `global.nc` (GFS 0.25°) + `conus.nc` (HRRR 6km)
- `utils.py` — shared utilities

## Prerequisites

- Azure subscription with:
  - Azure ML workspace + attached ACR (the workspace's built-in registry)
  - GPU quota in the workspace region: `Standard_NC40ads_H100_v5` (H100 80GB) or fallback `Standard_NC24ads_A100_v4` (A100 80GB) — at least 1 instance
- The environment **`nested-eagle-inference:10`** already built in the workspace (built in AML Studio from this Dockerfile + conda.yaml)
- The model **`nested-eagle:2`** registered containing both:
  - `inference-last.ckpt`
  - `hrrr_06km.nc`
- The managed identity has the GeoCatalog + Storage Blob roles requested for ingestion

## Quickstart (async — recommended)

```bash
cd ai-foundry

# 1. Create the endpoint (~5 min)
az ml online-endpoint create \
  -f endpoint.yml \
  -g epic-vnet \
  -w Eagle

# 2. Create the deployment (~15-25 min first time — GPU provisioning + image pull)
az ml online-deployment create \
  -f deployment.yml \
  -g epic-vnet \
  -w Eagle \
  --all-traffic

# 3. Capture URI + key
export SCORING_URI=$(az ml online-endpoint show -n nested-eagle-async -g epic-vnet -w Eagle --query scoring_uri -o tsv)
export SCORING_KEY=$(az ml online-endpoint get-credentials -n nested-eagle-async -g epic-vnet -w Eagle --query primaryKey -o tsv)

# 4. Health check
python test_client.py ping

# 5. Submit a forecast and auto-poll until done
python test_client.py run \
  --gfs   "az://initialconditions/gfs/2026-05-13T00.zarr" \
  --hrrr  "az://initialconditions/hrrr/2026-05-13T00.zarr" \
  --ic    "2026-05-13T00" \
  --lead  240
```

See [`README_async.md`](./README_async.md) for the full request/response contract, concurrency model, blob-upload setup, and what to put in the Foundry model card.

## Synchronous variant (legacy)

The original `score.py` keeps the request open until inference finishes (5-8 min). This **will not work** through a managed online endpoint's HTTP gateway because requests are cut off at 180s. It's kept here for:
- Direct unit testing of inference logic
- Reuse from the AML pipeline (`poc/pipeline.py`) where there's no HTTP layer
- Reference

Real Foundry submissions must use `score_async.py`.

## Notes

- **Preprocessing not included.** Callers supply pre-processed GFS + HRRR initial conditions as Zarr URLs. See `poc/preproc.py` for the prep pipeline.
- **Output files** are written to `/tmp/nested-eagle-output/` inside the container; set `UPLOAD_RESULTS=true` + blob env vars in `deployment.yml` to push NetCDFs to Azure Blob and return signed URLs in the status response.
- **Cost:** Holds a GPU 24/7 while the endpoint is active. H100 ≈ $25-30k/mo, A100 ≈ $3-4k/mo. For Foundry registration alone (no sustained traffic expected), the A100 path is the same UX at much lower cost.
- **NRT pipeline vs. endpoint.** NOAA's operational 6-hourly NRT pipeline lives in `aml/` + `poc/pipeline.py` and writes directly to GeoCatalog. This endpoint is the **separate on-demand inference path** required by Foundry.
