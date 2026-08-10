FROM mcr.microsoft.com/azureml/openmpi4.1.0-cuda11.8-cudnn8-ubuntu22.04:latest

# Install conda environment
COPY conda.yml /tmp/conda.yml
RUN conda env update -n base -f /tmp/conda.yml && \
    conda clean -afy

# flash-attn needs separate install with no-build-isolation
RUN pip install 'flash-attn<2.8' --no-build-isolation --no-cache-dir