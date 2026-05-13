"""
Ingest STAC Items into a Microsoft Planetary Computer Pro GeoCatalog.

After the pipeline uploads forecast data + STAC Items to blob storage,
this module POSTs the STAC Items to the GeoCatalog ingestion API so they
become discoverable via the STAC search endpoint.

GeoCatalog asynchronously copies the referenced data assets into its own
managed storage and indexes the STAC metadata.

Reference:
  https://learn.microsoft.com/en-us/azure/planetary-computer/add-stac-item-to-collection

Usage (standalone):
  ingest_stac_items(ic_timestamp, version, geocatalog_url, collection_id)
"""

import os
import time
from datetime import datetime

import requests
from azure.identity import DefaultAzureCredential

import stac_item

from config import (
    GEOCATALOG_AUDIENCE,
    API_VERSION,
    POLL_INTERVAL_SECONDS,
    MAX_POLL_ATTEMPTS,
)


def _get_auth_headers(credential):
    """Get an Authorization header with a bearer token for GeoCatalog."""
    token = credential.get_token(f"{GEOCATALOG_AUDIENCE}/.default")
    return {"Authorization": f"Bearer {token.token}"}


def _get_credential():
    """
    Build a DefaultAzureCredential with optional user-assigned MI pinning.

    If AZURE_CLIENT_ID is set, DefaultAzureCredential will use that managed
    identity in cloud environments that support MI. If not set, the default
    chain is used, which keeps local development behavior intact.
    """
    mi_client_id = os.getenv("AZURE_CLIENT_ID")

    credential = DefaultAzureCredential(
        managed_identity_client_id=mi_client_id,
        exclude_interactive_browser_credential=True,
    )

    if mi_client_id:
        print(f"  Auth: using managed identity client id from AZURE_CLIENT_ID")
    else:
        print("  Auth: using DefaultAzureCredential chain (AZURE_CLIENT_ID not set)")

    return credential


def _post_items(geocatalog_url, collection_id, items, headers):
    """
    POST an ItemCollection to the GeoCatalog ingestion endpoint.

    Returns the response object. A 202 status indicates items were accepted.
    """
    url = (
        f"{geocatalog_url}/stac/collections/{collection_id}/items"
        f"?api-version={API_VERSION}"
    )

    item_collection = {"type": "FeatureCollection", "features": items}

    print(f"  POSTing {len(items)} STAC item(s) to {url}")
    response = requests.post(url, headers=headers, json=item_collection, timeout=30)

    if response.status_code == 202:
        print(f"  Accepted (202). Ingestion started.")
    else:
        print(f"  ERROR: {response.status_code} — {response.text}")

    return response


def _poll_ingestion(location_url, headers):
    """Poll the ingestion workflow until it completes or times out."""
    print(f"  Polling ingestion status...")
    for attempt in range(MAX_POLL_ATTEMPTS):
        response = requests.get(location_url, headers=headers, timeout=30)
        status = response.json().get("status", "Unknown")
        print(f"    [{datetime.utcnow().isoformat()}] {status}")

        if status not in ("Pending", "Running"):
            return status

        time.sleep(POLL_INTERVAL_SECONDS)

    print("  WARNING: Polling timed out. Ingestion may still be in progress.")
    return "Timeout"


def ingest_stac_items(
    ic_timestamp,
    version,
    geocatalog_url,
    collection_id,
    output_storage_url,
    sas_token=None,
):
    """
    Generate and ingest STAC Items for a forecast cycle into GeoCatalog.

    Steps:
      1. Create raw + post-processed STAC Items (same as stac_item.py)
      2. If a SAS token is provided, append it to asset HREFs so GeoCatalog
         can copy the data from blob storage
      3. POST items to the GeoCatalog ingestion API
      4. Poll until ingestion completes

    Args:
        ic_timestamp: Forecast initialization timestamp.
        version: Model version string.
        geocatalog_url: GeoCatalog endpoint (no trailing slash, no /api).
        collection_id: STAC collection ID in GeoCatalog.
        output_storage_url: Blob storage base URL where data was uploaded.
        sas_token: Optional SAS token for blob access. If the GeoCatalog's
            managed identity already has Storage Blob Data Reader on the
            storage account, this is not needed.
    """
    geocatalog_url = geocatalog_url.rstrip("/")
    print(f"Ingesting STAC items into GeoCatalog: {geocatalog_url}")
    print(f"  Collection: {collection_id}")
    print(f"  Forecast cycle: {ic_timestamp}")

    # Build STAC items
    pp_item = stac_item.create_postprocessed_stac_item(
        ic_timestamp, version, output_storage_url
    )

    items = [pp_item]

    # Append SAS token to asset HREFs if provided
    if sas_token:
        for item in items:
            for asset in item.get("assets", {}).values():
                href = asset["href"]
                separator = "&" if "?" in href else "?"
                asset["href"] = f"{href}{separator}{sas_token}"

    # Authenticate
    credential = _get_credential()
    headers = _get_auth_headers(credential)

    # POST items
    response = _post_items(geocatalog_url, collection_id, items, headers)

    if response.status_code != 202:
        print(f"  Ingestion failed. Status: {response.status_code}")
        return False

    # Poll for completion
    location = response.headers.get("location")
    if location:
        print(f"  Ingestion status URL: {location}")
        # Refresh token for polling (may need fresh headers)
        headers = _get_auth_headers(credential)
        status = _poll_ingestion(location, headers)
        if status == "Succeeded":
            print("  Ingestion completed successfully.")
            return True
        else:
            print(f"  Ingestion ended with status: {status}")
            return False
    else:
        print("  No location header returned. Cannot poll status.")
        return True
