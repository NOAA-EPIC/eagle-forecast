"""
Ingest Nested-EAGLE STAC Items into Planetary Computer GeoCatalog.

This module creates one STAC Item for each forecast domain (global + CONUS),
submits each item to its target collection ingestion endpoint, and polls the
asynchronous ingestion status until completion.

GeoCatalog ingestion copies referenced assets and indexes STAC metadata.

Reference:
  https://learn.microsoft.com/en-us/azure/planetary-computer/add-stac-item-to-collection

Usage (standalone):
  ingest_stac_items(
      ic_timestamp,
      version,
      geocatalog_url,
      conus_collection_id,
      global_collection_id,
      output_storage_url,
  )
"""

import json
import os
import time
from datetime import datetime

import requests
import stac_item
from azure.identity import DefaultAzureCredential
from config import (
    API_VERSION,
    GEOCATALOG_AUDIENCE,
    MAX_POLL_ATTEMPTS,
    POLL_INTERVAL_SECONDS,
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
    POST a GeoJSON FeatureCollection to a GeoCatalog ingestion endpoint.

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

        print(f"\n    Poll attempt {attempt + 1}")
        print(f"    HTTP {response.status_code}")
        print(f"    Headers: {dict(response.headers)}")

        try:
            payload = response.json()
            print("    Body:")
            print(json.dumps(payload, indent=2))
        except Exception:
            print("    Non-JSON body:")
            print(response.text)
            payload = {}

        status = payload.get("status", "Unknown")
        print(f"    [{datetime.utcnow().isoformat()}] {status}")

        if status not in ("Pending", "Running"):
            return status, payload

        time.sleep(POLL_INTERVAL_SECONDS)

    print("  WARNING: Polling timed out. Ingestion may still be in progress.")
    return "Timeout", {}


def _ingest_single_item(geocatalog_url, collection_id, item, credential):
    """Ingest one STAC item and return True when ingestion succeeds."""
    item_id = item.get("id", "<unknown-id>")
    headers = _get_auth_headers(credential)
    print(f"\nIngesting item: {item_id}")

    response = _post_items(geocatalog_url, collection_id, [item], headers)
    if response.status_code != 202:
        print(f"  Ingestion failed for {item_id}. Status: {response.status_code}")
        try:
            print(json.dumps(response.json(), indent=2))
        except Exception:
            print(response.text)
        return False

    location = response.headers.get("location")
    if not location:
        print(f"  No location header returned for {item_id}. Cannot poll status.")
        return False

    print(f"  Ingestion status URL: {location}")
    headers = _get_auth_headers(credential)
    status, payload = _poll_ingestion(location, headers)
    if status == "Succeeded":
        print(f"  Ingestion completed successfully for {item_id}.")
        return True

    print(f"  Ingestion ended with status {status} for {item_id}.")
    if payload.get("error"):
        print("  Error details:")
        print(json.dumps(payload.get("error"), indent=2))
    return False


def ingest_stac_items(
    ic_timestamp,
    version,
    geocatalog_url,
    conus_collection_id,
    global_collection_id,
    output_storage_url,
    sas_token=None,
):
    """
    Generate and ingest STAC Items for one forecast cycle.

    Steps:
      1. Create post-processed STAC Items (global + CONUS)
      2. If a SAS token is provided, append it to asset HREFs so GeoCatalog
         can copy the data from blob storage
      3. Ingest each item into its configured collection
      4. Poll each ingestion operation until completion

    Args:
        ic_timestamp: Forecast initialization timestamp.
        version: Model version string.
        geocatalog_url: GeoCatalog endpoint (no trailing slash, no /api).
        conus_collection_id: STAC collection ID for CONUS items.
        global_collection_id: STAC collection ID for global items.
        output_storage_url: Blob storage base URL where data was uploaded.
        sas_token: Optional SAS token for blob access. If the GeoCatalog's
            managed identity already has Storage Blob Data Reader on the
            storage account, this is not needed.
    """
    geocatalog_url = geocatalog_url.rstrip("/")
    print(f"Ingesting STAC items into GeoCatalog: {geocatalog_url}")
    print(f"  Forecast cycle: {ic_timestamp}")

    # Build STAC items
    items = stac_item.create_postprocessed_stac_items(
        ic_timestamp, version, output_storage_url
    )

    global_item = items[0]
    conus_item = items[1]

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

    item_results = {}

    conus_item_id = conus_item.get("id", "<unknown-id>")
    item_results[conus_item_id] = _ingest_single_item(
        geocatalog_url=geocatalog_url,
        collection_id=conus_collection_id,
        item=conus_item,
        credential=credential,
    )

    global_item_id = global_item.get("id", "<unknown-id>")
    item_results[global_item_id] = _ingest_single_item(
        geocatalog_url=geocatalog_url,
        collection_id=global_collection_id,
        item=global_item,
        credential=credential,
    )

    succeeded = [item_id for item_id, ok in item_results.items() if ok]
    failed = [item_id for item_id, ok in item_results.items() if not ok]

    print("\nIngestion summary:")
    print(f"  Succeeded: {len(succeeded)}")
    for item_id in succeeded:
        print(f"    - {item_id}")
    print(f"  Failed: {len(failed)}")
    for item_id in failed:
        print(f"    - {item_id}")

    return len(failed) == 0
