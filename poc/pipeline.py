"""
Build and run the Nested-EAGLE Azure ML near-real-time pipeline.

Pipeline graph:
  1. Resolve cycle time (CPU): choose one 6-hour UTC cycle timestamp
  2. Preprocess (CPU): load GFS/HRRR initial conditions to Zarr
  3. Inference (GPU): run Nested-EAGLE forecast
  4. Postprocess + STAC + ingest (CPU): produce domain NetCDFs, write STAC
     Items, and ingest into Planetary Computer GeoCatalog collections

Usage:
  cd poc
  python pipeline.py              # submit a single test run
  python pipeline.py --schedule   # create/enable the 6h recurring schedule
"""

import argparse
from datetime import datetime, timedelta, timezone

from azure.ai.ml import Input, Output, command, dsl
from azure.ai.ml.constants import TimeZone
from azure.ai.ml.entities import (
    CronTrigger,
    JobSchedule,
)
from config import (
    CLIENT_ID,
    CPU_CLUSTER_NAME,
    GPU_CLUSTER_NAME,
    IC_STORAGE_ACCOUNT,
    INFERENCE_ENVIRONMENT_NAME,
    INFERENCE_ENVIRONMENT_VERSION,
    LEAD_TIME,
    MODEL_NAME,
    MODEL_VERSION,
    PREPROC_ENVIRONMENT_NAME,
    PREPROC_ENVIRONMENT_VERSION,
    STORAGE_ACCOUNT,
    VERSION,
    get_managed_identity_client,  # use for scheduled runs in Azure
    get_ml_client,  # use for local/manual test submissions
)

resolve_cycle_time_component = command(
    code=".",
    command=(
        "python resolve_init_time.py "
        "--output ${{outputs.run_context}} "
        "$[[--cycle_time_override ${{inputs.cycle_time_override}}]]"
    ),
    environment=f"{PREPROC_ENVIRONMENT_NAME}:{PREPROC_ENVIRONMENT_VERSION}",
    compute=CPU_CLUSTER_NAME,
    display_name="nested-eagle-resolve-cycle-time",
    experiment_name="nested-eagle-resolve-cycle-time",
    inputs={
        "cycle_time_override": Input(type="string", optional=True),
    },
    outputs={
        "run_context": Output(type="uri_file"),
    },
    description="Resolve one UTC 6h cycle time for the whole pipeline run.",
    tags={
        "eagle": "nested-eagle",
        "pipeline_stage": "preprocessing",
    },
)

preproc_component = command(
    code=".",
    command=(
        "python preproc.py "
        "--output_dir ${{outputs.initial_conditions}} "
        "--run_context ${{inputs.run_context}}"
    ),
    environment=f"{PREPROC_ENVIRONMENT_NAME}:{PREPROC_ENVIRONMENT_VERSION}",
    compute=CPU_CLUSTER_NAME,
    display_name="nested-eagle-preproc",
    experiment_name="nested-eagle-preproc",
    inputs={
        "run_context": Input(type="uri_file"),
    },
    outputs={
        "initial_conditions": Output(
            type="uri_folder",
            mode="rw_mount",
            path=f"azureml://datastores/{IC_STORAGE_ACCOUNT}/paths/{VERSION}/",
        )
    },
    description="Download GFS + HRRR, regrid HRRR to 6km, write both to Zarr",
    tags={
        "eagle": "nested-eagle",
        "pipeline_stage": "preprocessing",
    },
)

inference_component = command(
    code=".",
    command=(
        "python inference.py "
        "--output_dir ${{outputs.raw_inference}} "
        "--input_dir ${{inputs.initial_conditions}} "
        "--checkpoint ${{inputs.model}} "
        "--run_context ${{inputs.run_context}}"
    ),
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
        "run_context": Input(type="uri_file"),
    },
    description=f"Run {LEAD_TIME}h forecast and write NetCDF.",
    tags={
        "eagle": "nested-eagle",
        "pipeline_stage": "inference",
    },
)

postproc_component = command(
    code=".",
    command=(
        "python postproc.py "
        "--output_dir ${{outputs.postprocessed_inference}} "
        "--stac_items ${{outputs.stac_items}} "
        "--initial_conditions ${{inputs.initial_conditions}} "
        "--raw_inference ${{inputs.raw_inference}} "
        "--run_context ${{inputs.run_context}}"
    ),
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
        "run_context": Input(type="uri_file"),
    },
    description="Postprocess inference to global/CONUS NetCDFs, write STAC items, and ingest into Planetary Computer.",
    environment_variables={
        "AZURE_CLIENT_ID": CLIENT_ID,
    },
    tags={
        "eagle": "nested-eagle",
        "pipeline_stage": "postprocessing",
    },
)


@dsl.pipeline(
    name="nested-eagle-nrt-pipeline",
    description="Nested-EAGLE NRT: 6h weather forecast pipeline",
)
def nested_eagle_pipeline(cycle_time_override: str = None):
    """4-step pipeline: resolve cycle → preprocess → inference → postprocess/ingest."""

    cycle_step = resolve_cycle_time_component(cycle_time_override=cycle_time_override)

    preproc_step = preproc_component(run_context=cycle_step.outputs.run_context)

    inference_step = inference_component(
        initial_conditions=preproc_step.outputs.initial_conditions,
        run_context=cycle_step.outputs.run_context,
    )

    postproc_step = postproc_component(
        raw_inference=inference_step.outputs.raw_inference,
        initial_conditions=preproc_step.outputs.initial_conditions,
        run_context=cycle_step.outputs.run_context,
    )

    return {}


def submit_test_run(ml_client):
    """Submit a single test pipeline run."""
    print("Submitting test pipeline run...")
    pipeline_job = nested_eagle_pipeline()
    # Disable cached-output reuse for every pipeline step.
    pipeline_job.settings.force_rerun = True
    pipeline_job = ml_client.jobs.create_or_update(
        pipeline_job,
        experiment_name="nested-eagle-nrt",
    )
    print(f"  Job name:   {pipeline_job.name}")
    print(f"  Status:     {pipeline_job.status}")
    print(f"  Studio URL: {pipeline_job.studio_url}")
    print()
    print("Monitor the pipeline in the AML Studio URL above.")
    print("Once validated, enable the schedule with: python pipeline.py --schedule")


def create_schedule(ml_client):
    """Create or update and enable the 6-hour UTC AML pipeline schedule."""
    now = datetime.now(timezone.utc)
    start_time = (
        now.replace(minute=0, second=0, microsecond=0)
        + timedelta(hours=6 - (now.hour % 6))
    ).replace(tzinfo=None)

    schedule_name = "nested-eagle-6hr-pipeline"

    print("Creating 6-hour UTC cron schedule...")

    pipeline_job = nested_eagle_pipeline()
    pipeline_job.settings.force_rerun = True
    pipeline_job.experiment_name = schedule_name

    schedule = JobSchedule(
        name=schedule_name,
        trigger=CronTrigger(
            expression="0 0,6,12,18 * * *",
            start_time=start_time,
            time_zone=TimeZone.UTC,
        ),
        create_job=pipeline_job,
    )

    returned_schedule = ml_client.schedules.begin_create_or_update(schedule).result()

    if not returned_schedule.is_enabled:
        returned_schedule = ml_client.schedules.begin_enable(
            name=schedule_name
        ).result()

    if returned_schedule.provisioning_state != "Succeeded":
        raise RuntimeError(
            f"Schedule provisioning failed: {returned_schedule.provisioning_state}"
        )

    print(f"Schedule name:      {returned_schedule.name}")
    print(f"Enabled:            {returned_schedule.is_enabled}")
    print(f"Provisioning state: {returned_schedule.provisioning_state}")
    print("Runs:               00:00, 06:00, 12:00, 18:00 UTC")


def main():
    """CLI entry point for one-off submission or recurring schedule setup."""
    parser = argparse.ArgumentParser(description="Nested-EAGLE AML Pipeline")
    parser.add_argument(
        "--schedule",
        action="store_true",
        help="Create the 6h recurring schedule (instead of a single test run)",
    )
    args = parser.parse_args()


    if args.schedule:
        ml_client = get_managed_identity_client()
        create_schedule(ml_client)
    else:
        ml_client = get_ml_client()
        submit_test_run(ml_client)
        
    print(f"Connected to workspace: {ml_client.workspace_name}\n")


if __name__ == "__main__":
    main()
