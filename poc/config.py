from azure.ai.ml import MLClient
from azure.identity import DefaultAzureCredential

# permissions, etc.
SUBSCRIPTION_ID = "PLACEHOLDER"
RESOURCE_GROUP = "PLACEHOLDER"
WORKSPACE_NAME = "PLACEHOLDER"

def get_ml_client() -> MLClient:
    """Create and return an authenticated MLClient."""
    credential = DefaultAzureCredential()
    return MLClient(
        credential=credential,
        subscription_id=SUBSCRIPTION_ID,
        resource_group_name=RESOURCE_GROUP,
        workspace_name=WORKSPACE_NAME,
    )

# general
LEAD_TIME = 240
FREQ = "6h"
VERSION = "1.0"

# preproc vars
MULTISTEP_INPUT = True
IC_STORAGE_ACCOUNT = "PLACEHOLDER"

# inference vars
TRIM_EDGE = [25, 24, 25, 26]
MIN_DISTANCE_KM = 6
MODEL_NAME = "PLACEHOLDER"
MODEL_VERSION = "PLACEHOLDER"

# compute
CPU_CLUSTER_NAME = "eagle-cpu"
GPU_CLUSTER_NAME = "eagle-gpu-h100"

PREPROC_ENVIRONMENT_NAME = "nrt_preproc"
PREPROC_ENVIRONMENT_VERSION = "3"

INFERENCE_ENVIRONMENT_NAME = "nested-eagle-inference"
INFERENCE_ENVIRONMENT_VERSION = "10"

# storage account
STORAGE_ACCOUNT = "PLACEHOLDER"
CONTAINER = "PLACEHOLDER"
OUTPUT_STORAGE_URL = f"https://{STORAGE_ACCOUNT}.blob.core.windows.net/{CONTAINER}"

# geocatalog
GEOCATALOG_URL = "PLACEHOLDER"
COLLECTION_ID = "PLACEHOLDER"

# Bounding boxes [west, south, east, north]
BBOX_GLOBAL = [-180.0, -89.75, 180.0, 89.75]
BBOX_CONUS = [-131.52061, 22.74829, -63.603, 51.31966]

# Variables output by the model (14 total)
VARIABLES = [
    "10m_meridional_wind",
    "10m_zonal_wind",
    "2m_specific_humidity",
    "2m_temperature",
    "80m_meridional_wind",
    "80m_zonal_wind",
    "geopotential_height",
    "meridional_wind",
    "specific_humidity",
    "surface_pressure",
    "surface_temperature",
    "temperature",
    "total_precipitation_6hr",
    "vertical_velocity",
    "zonal_wind",
]

PRESSURE_LEVELS = [100, 150, 200, 250, 300, 400, 500, 600, 700, 850, 925, 1000]

GEOCATALOG_AUDIENCE = "https://geocatalog.spatio.azure.com"
API_VERSION = (
    "2026-04-15"  # get this from your geocatalog, not your APIM
)
POLL_INTERVAL_SECONDS = 15
MAX_POLL_ATTEMPTS = 80  # 5 minutes max
