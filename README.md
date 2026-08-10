# eagle-forecast

Workflows for running Nested-EAGLE forecasts in near-real-time (NRT) operations
on Azure Machine Learning (AML), with STAC metadata ingestion into Planetary
Computer GeoCatalog.

## Scope

The operational proof-of-concept (POC) lives in `poc/`. The pipeline orchestrates:

1. Cycle-time resolution (single UTC 6-hour cycle per run)
2. Initial-condition preprocessing (GFS + HRRR to Zarr)
3. GPU inference
4. Postprocessing, STAC item creation, and GeoCatalog ingestion

## Repository Layout

- `poc/pipeline.py` - AML pipeline definition, test submission, and schedule creation
- `poc/resolve_init_time.py` - resolves `nrt_timestamp` for all downstream steps
- `poc/preproc.py` - prepares GFS/HRRR initial conditions
- `poc/inference.py` - runs Nested-EAGLE inference
- `poc/postproc.py` - builds domain NetCDF outputs + STAC + ingestion calls
- `poc/stac_item.py` - creates global and CONUS STAC Items
- `poc/pc_ingest.py` - ingests STAC items into GeoCatalog collections
- `poc/config.py` - central configuration and placeholders
- `poc/stac_collection_global.json` / `poc/stac_collection_conus.json` - collection templates

## Security and Placeholders

`PLACEHOLDER` values in `poc/config.py` are intentional. Keep private AML,
subscription, storage, and identity details out of source control.

Before running anything, populate the placeholders in your private environment.

## Runtime Prerequisites

Use two dependency layers:

- **Control-plane (submit pipeline jobs):**
  - Python 3.12+
  - `azure-ai-ml`
  - `azure-identity`
- **Data-plane/component execution (local component testing only):**
  - `ufs2arco`
  - `anemoi-*` libraries
  - `eagle-tools`
  - `xarray`, `h5netcdf`, `pyproj`, `rioxarray`, `requests`, `pandas`, `yaml`

In AML production runs, dependencies are primarily provided by the registered
AML environments configured in `config.py`.

### Minimal Submitter Environment (Job Submission Only)

If your goal is only to submit/test/schedule AML pipeline jobs from your local
machine, this is sufficient:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install azure-ai-ml azure-identity
```

You do **not** need `ufs2arco`, `anemoi-*`, or other heavy runtime packages to
submit jobs, because AML compute executes component code in the registered AML
environments.

Optional but commonly needed for auth in local submission workflows:

```bash
az login
az extension add -n ml --upgrade
```

Set the subscription and defaults once so `az ml` commands target the right workspace:

```bash
az account set --subscription "<SUBSCRIPTION_ID>"
az configure --defaults group="<RESOURCE_GROUP>" workspace="<WORKSPACE_NAME>"
```

## One-Time Setup

From repo root:

```bash
cd poc
python config/hrrr_6km.py
```

This generates the static HRRR 6 km target grid used by preprocessing/regridding
configuration.

Note: generating this file requires runtime packages like `ufs2arco` and
`xarray` (not just the minimal submitter environment).

## Configure `poc/config.py`

At minimum, set:

- AML workspace identifiers:
  - `SUBSCRIPTION_ID`
  - `RESOURCE_GROUP`
  - `WORKSPACE_NAME`
- Compute and environment settings:
  - `CPU_CLUSTER_NAME`
  - `GPU_CLUSTER_NAME`
  - environment names/versions
- Data locations:
  - `IC_STORAGE_ACCOUNT`
  - `STORAGE_ACCOUNT`
  - `CONTAINER`
- Model registry refs:
  - `MODEL_NAME`
  - `MODEL_VERSION`
- GeoCatalog configuration:
  - `GEOCATALOG_URL`
  - `GLOBAL_COLLECTION_ID`
  - `CONUS_COLLECTION_ID`
  - `API_VERSION`
- Identity:
  - `CLIENT_ID` (user-assigned MI client id if used)

## How to Make AML Environments

The pipeline expects two registered AML environments:

- CPU/preprocessing environment:
  - Name/version from `PREPROC_ENVIRONMENT_NAME` and `PREPROC_ENVIRONMENT_VERSION`
  - Conda spec: `poc/envs/cpu/conda.yml`
- GPU/inference environment:
  - Name/version from `INFERENCE_ENVIRONMENT_NAME` and `INFERENCE_ENVIRONMENT_VERSION`
  - Build context: `poc/envs/gpu/` (`Dockerfile` + `conda.yml`)

Create/register both with Azure CLI:

```bash
cd poc
RG="<RESOURCE_GROUP>"
WS="<WORKSPACE_NAME>"

# CPU environment from conda spec + base AML image
az ml environment create \
  --resource-group "$RG" \
  --workspace-name "$WS" \
  --name "nrt_preproc" \
  --version "7" \
  --image "mcr.microsoft.com/azureml/openmpi4.1.0-ubuntu22.04:latest" \
  --conda-file "envs/cpu/conda.yml"

# GPU environment from build context (envs/gpu/Dockerfile + conda.yml)
az ml environment create \
  --resource-group "$RG" \
  --workspace-name "$WS" \
  --name "nested-eagle-inference" \
  --version "10" \
  --file "envs/gpu/environment.yml"
```

Notes:

- Run this from `poc/` so relative paths resolve correctly.
- Keep the environment names/versions in `config.py` synchronized with what you register.
- If your `config.py` uses different names/versions than shown above, update the CLI flags accordingly.
- GPU image build can take several minutes (it installs `flash-attn` during image build).

## How to Make AML Compute Clusters

Create the two AML compute clusters used by the pipeline steps:

- GPU cluster size: `Standard_NC24ads_A100_v4` (24 cores, 220 GB RAM, 64 GB disk)
- CPU cluster size: `Standard_D16ds_v5` (16 cores, 64 GB RAM, 600 GB disk)

Example CLI commands:

```bash
cd poc
RG="<RESOURCE_GROUP>"
WS="<WORKSPACE_NAME>"
REGION="<WORKSPACE_REGION>"

# GPU compute for inference step
az ml compute create \
  --resource-group "$RG" \
  --workspace-name "$WS" \
  --location "$REGION" \
  --name "nested-eagle-gpu" \
  --type "amlcompute" \
  --size "Standard_NC24ads_A100_v4" \
  --min-instances 0 \
  --max-instances 1

# CPU compute for resolve/preprocess/postprocess steps
az ml compute create \
  --resource-group "$RG" \
  --workspace-name "$WS" \
  --location "$REGION" \
  --name "nested-eagle-cpu" \
  --type "amlcompute" \
  --size "Standard_D16ds_v5" \
  --min-instances 0 \
  --max-instances 2
```

If you omit `--location`, AML uses the workspace region by default.

After creation, set these names in `poc/config.py`:

- `GPU_CLUSTER_NAME` -> your GPU cluster name (for example `nested-eagle-gpu`)
- `CPU_CLUSTER_NAME` -> your CPU cluster name (for example `nested-eagle-cpu`)

## Run the AML Pipeline

Always run from `poc/` so component `code="."` and relative script paths resolve
correctly.

### Submit one test run

```bash
cd poc
python pipeline.py
```

### Create/enable 6-hour schedule

```bash
cd poc
python pipeline.py --schedule
```

The schedule runs at `00:00`, `06:00`, `12:00`, and `18:00` UTC.

## Data and STAC Outputs

Per cycle timestamp (`YYYY/MM/DD/HH`):

- Raw inference:
  - `.../data/raw/{cycle}/...`
- Postprocessed:
  - `.../data/postprocessed/{cycle}/nested-global.{YYYY-MM-DDTHH}.{LEAD_TIME}h.nc`
  - `.../data/postprocessed/{cycle}/nested-lam.{YYYY-MM-DDTHH}.{LEAD_TIME}h.nc`
- STAC items:
  - `.../stac/items/{cycle}/nested-eagle-global-{YYYYMMDD-HH}z.json`
  - `.../stac/items/{cycle}/nested-eagle-conus-{YYYYMMDD-HH}z.json`

## Cycle-Time Resolution (Scheduled vs Manual)

When run through `pipeline.py`, cycle time is resolved centrally by
`resolve_init_time.py` and passed to each step via `run_context`.

When running `preproc.py`, `inference.py`, or `postproc.py` directly,
`--run_context` is optional:

- If `--run_context` is provided, that timestamp is used.
- If omitted, scripts fall back to `utils.get_nrt_timestamp()`.

For historical/backfill manual runs, set `MANUAL_IC_TIMESTAMP` in
`poc/utils.py` to a specific UTC timestamp (for example
`"2026-07-28T06:00:00Z"`). The helper normalizes it to a 6-hour cycle.

## How Ingestion Works

`postproc.py` calls `pc_ingest.ingest_stac_items(...)`, which:

1. Builds global + CONUS STAC items from the cycle timestamp
2. Optionally appends SAS to asset hrefs
3. Calls GeoCatalog ingestion API for each target collection
4. Polls each asynchronous ingestion operation and prints status/errors

Important behavior:

- Items are ingested via API calls, not by auto-discovering files in blob.
- Item `collection` and the ingestion endpoint collection path must match.
- `stac_collection_*.json` files are templates/reference artifacts; they are not
  auto-registered by this code path.

## Managed Identity and Permissions

Two identities may be involved:

1. **AML job identity** (used by `pc_ingest.py`):
   - Authenticates to GeoCatalog API via `DefaultAzureCredential`
   - If `AZURE_CLIENT_ID` is set, the credential pins to that user-assigned MI
2. **GeoCatalog managed identity** (used by service-side asset copy):
   - Needs read access to storage assets in item `href`
   - Alternative: append a SAS token to hrefs at ingest time

`pipeline.py` sets `AZURE_CLIENT_ID` on the postprocess component using `CLIENT_ID`.

## Troubleshooting "Accepted but Not Visible"

If ingestion returns `202` but items do not appear:

1. Check final polled ingestion status in logs (must end as `Succeeded`)
2. Confirm GeoCatalog identity can read referenced blob assets (or SAS is present)
3. Confirm `GLOBAL_COLLECTION_ID` / `CONUS_COLLECTION_ID` exist in GeoCatalog
4. Confirm STAC item paths, links, and extension fields are valid
5. Verify API version and audience settings in `config.py`

## STAC Reference

For Planetary Computer STAC concepts (Catalog/Collection/Item/API), see:
[STAC framework in Microsoft Planetary Computer Pro](https://learn.microsoft.com/en-us/azure/planetary-computer/stac-overview)
