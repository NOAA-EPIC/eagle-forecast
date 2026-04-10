"""
Build the 3-step AML pipeline and enable the 6h schedule.

This script:
  1. Defines a 3-step pipeline:
     - Step 1 (CPU): preprocessing — download GFS/HRRR, regrid, write Zarr
     - Step 2 (GPU): inference
     - Step 3 (CPU): postprocess to separate global + CONUS netcdf files, upload to blob, write STAC, write to PC
  2. Submits a test pipeline run
  3. Optionally creates a 6h recurring schedule

Usage:
  python aml/pipeline.py              # Submit a single test run
  python aml/pipeline.py --schedule   # Create the 6h recurring schedule
"""

import argparse

from config import (
    get_ml_client,
    CPU_CLUSTER_NAME,
    GPU_CLUSTER_NAME,
    PREPROC_ENVIRONMENT_NAME,
    PREPROC_ENVIRONMENT_VERSION,
    INFERENCE_ENVIRONMENT_NAME,
    INFERENCE_ENVIRONMENT_VERSION,
    VERSION,
    STORAGE_ACCOUNT,
    IC_STORAGE_ACCOUNT,
    MODEL_NAME,
    MODEL_VERSION,
    LEAD_TIME,
)

from azure.ai.ml import command, dsl, Input, Output
from azure.ai.ml.entities import RecurrenceTrigger, JobSchedule


preproc_component = command(
    code=".",
    command="python preproc.py --output_dir ${{outputs.initial_conditions}}",
    environment=f"{PREPROC_ENVIRONMENT_NAME}:{PREPROC_ENVIRONMENT_VERSION}",
    compute=CPU_CLUSTER_NAME,
    display_name="nested-eagle-preproc",
    experiment_name="nested-eagle-preproc",
    outputs={
        "initial_conditions": Output(
            type="uri_folder",
            mode="rw_mount",
            path=f"azureml://datastores/{IC_STORAGE_ACCOUNT}/paths/{VERSION}/",
        )
    },
    description="Download GFS + HRRR, regrid HRRR to 6km, write both to Zarr",
)

inference_component = command(
    code=".",
    command="python inference.py --output_dir ${{outputs.raw_inference}} --input_dir ${{inputs.initial_conditions}} --checkpoint ${{inputs.model}}",
    environment=f"{INFERENCE_ENVIRONMENT_NAME}:{INFERENCE_ENVIRONMENT_VERSION}",
    compute=GPU_CLUSTER_NAME,
    display_name="nested-eagle-inference",
    experiment_name="nested-eagle-inference",
    outputs={
        "raw_inference": Output(
            type="uri_folder",
            mode="rw_mount",
            path=f"azureml://datastores/{STORAGE_ACCOUNT}/paths/{VERSION}/data/raw/",
        ),
    },
    inputs={
        "initial_conditions": Input(
            type="uri_folder",
            mode="ro_mount",
            path=f"azureml://datastores/{IC_STORAGE_ACCOUNT}/paths/{VERSION}/",
        ),
        "model": Input(
            type="custom_model", path=f"azureml:{MODEL_NAME}:{MODEL_VERSION}"
        ),
    },
    description=f"Run {LEAD_TIME}h forecast and write NetCDF.",
)

postproc_component = command(
    code=".",
    command="python postproc.py --output_dir ${{outputs.postprocessed_inference}} --stac_items ${{outputs.stac_items}} --initial_conditions ${{inputs.initial_conditions}} --raw_inference ${{inputs.raw_inference}}",
    environment=f"{PREPROC_ENVIRONMENT_NAME}:{PREPROC_ENVIRONMENT_VERSION}",
    compute=CPU_CLUSTER_NAME,
    display_name="nested-eagle-postproc",
    experiment_name="nested-eagle-postproc",
    outputs={
        "postprocessed_inference": Output(
            type="uri_folder",
            mode="rw_mount",
            path=f"azureml://datastores/{STORAGE_ACCOUNT}/paths/{VERSION}/data/postprocessed/",
        ),
        "stac_items": Output(
            type="uri_folder",
            mode="rw_mount",
            path=f"azureml://datastores/{STORAGE_ACCOUNT}/paths/{VERSION}/stac/",
        ),
    },
    inputs={
        "initial_conditions": Input(
            type="uri_folder",
            mode="ro_mount",
            path=f"azureml://datastores/{IC_STORAGE_ACCOUNT}/paths/{VERSION}/",
        ),
        "raw_inference": Input(
            type="uri_folder",
            mode="rw_mount",
            path=f"azureml://datastores/{STORAGE_ACCOUNT}/paths/{VERSION}/data/raw/",
        ),
    },
    description="Posprocesses inference to separate global + CONUS files, generates STAC Items, uploads all to blob, triggers PC ingest.",
)


@dsl.pipeline(
    name="nested-eagle-nrt",
    description="Nested-EAGLE NRT: 6h weather forecast pipeline",
)
def nested_eagle_pipeline():
    """3-step pipeline: CPU preprocessing → GPU inference → CPU postprocessing"""

    preproc_step = preproc_component()

    inference_step = inference_component(
        initial_conditions=preproc_step.outputs.initial_conditions
    )

    postproc_step = postproc_component(
        raw_inference=inference_step.outputs.raw_inference,
        initial_conditions=preproc_step.outputs.initial_conditions,
    )

    return {}


def submit_test_run(ml_client):
    """Submit a single test pipeline run."""
    print("Submitting test pipeline run...")
    pipeline_job = ml_client.jobs.create_or_update(
        nested_eagle_pipeline(),
        experiment_name="nested-eagle-nrt",
    )
    print(f"  Job name:   {pipeline_job.name}")
    print(f"  Status:     {pipeline_job.status}")
    print(f"  Studio URL: {pipeline_job.studio_url}")
    print()
    print("Monitor the pipeline in the AML Studio URL above.")
    print("Once validated, enable the schedule with: python aml/pipeline.py --schedule")


def create_schedule(ml_client):
    """Create a 6h recurring schedule for the pipeline."""
    print("Creating 6h recurring schedule...")

    schedule = JobSchedule(
        name="nested-eagle-6h",
        trigger=RecurrenceTrigger(
            frequency="hour",
            interval=6,
            start_time="2026-04-01T00:00:00Z",
            time_zone="UTC",
        ),
        create_job=nested_eagle_pipeline(),
    )

    returned_schedule = ml_client.schedules.begin_create_or_update(schedule).result()
    print(f"  Schedule name:   {returned_schedule.name}")
    print(f"  Trigger:         Every 6 hours (00Z, 06Z, 12Z, 18Z)")
    print(f"  Status:          {returned_schedule.is_enabled}")
    print()
    print("Schedule is active. The pipeline will run every 6 hours.")
    print()
    print("To disable the schedule:")
    print("  ml_client.schedules.begin_disable('nested-eagle-6h')")
    print()
    print("To check schedule status:")
    print("  ml_client.schedules.get('nested-eagle-6h')")


def main():
    parser = argparse.ArgumentParser(description="Nested-EAGLE AML Pipeline")
    parser.add_argument(
        "--schedule",
        action="store_true",
        help="Create the 6h recurring schedule (instead of a single test run)",
    )
    args = parser.parse_args()

    ml_client = get_ml_client()
    print(f"Connected to workspace: {ml_client.workspace_name}\n")

    if args.schedule:
        create_schedule(ml_client)
    else:
        submit_test_run(ml_client)


if __name__ == "__main__":
    main()
