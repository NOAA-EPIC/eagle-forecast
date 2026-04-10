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
LEAD_TIME = 360
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

BBOX_GLOBAL = [-180.0, -90.0, 180.0, 90.0]
BBOX_CONUS = [-134.1, 21.1, -60.9, 52.6]

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
API_VERSION = "PLACEHOLDER"
POLL_INTERVAL_SECONDS = 5
MAX_POLL_ATTEMPTS = 60
