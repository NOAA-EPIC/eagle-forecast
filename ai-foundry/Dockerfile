# Nested-EAGLE inference container (Azure AI Foundry online endpoint)
# Base: Azure ML CUDA image with H100 support (CUDA 12.4, cuDNN 8)
FROM mcr.microsoft.com/azureml/openmpi5.0-cuda12.4-ubuntu22.04:latest

WORKDIR /app

# Install conda environment
COPY conda.yaml /tmp/conda.yaml
RUN conda env update -n base -f /tmp/conda.yaml && \
    conda clean -afy

# flash-attn requires separate install with no-build-isolation
RUN pip install 'flash-attn<2.8' --no-build-isolation --no-cache-dir

# Copy scoring script and inference helpers from poc/
COPY score.py /app/score.py

# AML managed online endpoint entry point
ENV AZUREML_ENTRY_SCRIPT=/app/score.py

# Checkpoint and grid file are mounted at runtime by AML model mount.
# Override with env vars if using a different mount path.
ENV CHECKPOINT_PATH=/mnt/models/inference-last.ckpt
ENV GRID_FILE=/mnt/models/hrrr_06km.nc
