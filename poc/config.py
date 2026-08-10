"""
Central configuration for the Nested-EAGLE AML proof-of-concept pipeline.

Values intentionally marked as PLACEHOLDER are environment-specific and should
be populated in your private deployment configuration.
"""

from azure.ai.ml import MLClient
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential


def get_ml_client() -> MLClient:
    """Create and return an authenticated MLClient."""
    credential = DefaultAzureCredential()
    return MLClient(
        credential=credential,
        subscription_id=SUBSCRIPTION_ID,
        resource_group_name=RESOURCE_GROUP,
        workspace_name=WORKSPACE_NAME,
    )


def get_managed_identity_client() -> MLClient:
    """Create an MLClient using managed identity authentication."""
    credential = ManagedIdentityCredential(
        client_id=CLIENT_ID
    )
    return MLClient(
        credential=credential,
        subscription_id=SUBSCRIPTION_ID,
        resource_group_name=RESOURCE_GROUP,
        workspace_name=WORKSPACE_NAME,
    )


LEAD_TIME = 240
FREQ = "6h"
VERSION = "1.0"
MULTISTEP_INPUT = True

TRIM_EDGE = [25, 24, 25, 26]
MIN_DISTANCE_KM = 6

SUBSCRIPTION_ID = "PLACEHOLDER"
RESOURCE_GROUP = "PLACEHOLDER"
WORKSPACE_NAME = "PLACEHOLDER"
CLIENT_ID = "PLACEHOLDER"

CPU_CLUSTER_NAME = "PLACEHOLDER"
GPU_CLUSTER_NAME = "PLACEHOLDER"

PREPROC_ENVIRONMENT_NAME = "nrt_preproc"
PREPROC_ENVIRONMENT_VERSION = "7"
INFERENCE_ENVIRONMENT_NAME = "nested-eagle-inference"
INFERENCE_ENVIRONMENT_VERSION = "10"

IC_STORAGE_ACCOUNT = "PLACEHOLDER"

MODEL_NAME = "nested-eagle"
MODEL_VERSION = "2"

STORAGE_ACCOUNT = "PLACEHOLDER"
CONTAINER = "PLACEHOLDER"
OUTPUT_STORAGE_URL = f"https://{STORAGE_ACCOUNT}.blob.core.windows.net/{CONTAINER}"

GEOCATALOG_URL = "PLACEHOLDER"
GLOBAL_COLLECTION_ID = "nested-eagle-global"
CONUS_COLLECTION_ID = "nested-eagle-conus"

# Bounding boxes [west, south, east, north]
BBOX_GLOBAL = [-180.0, -89.75, 180.0, 89.75]
BBOX_CONUS = [-131.53, 22.75, -63.61, 51.32]

# Variables output by the model (15 total)
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
    "2026-04-15"  # Get this from the GeoCatalog API version you are targeting.
)
POLL_INTERVAL_SECONDS = 15
MAX_POLL_ATTEMPTS = 80  # 20 minutes max at 15-second polling intervals.
