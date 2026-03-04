### POC for running nested-eagle in near-real time

This directory provides scripts to run nested-eagle in NRT. This directory is considered a POC to demonstrate how a NRT pipeline could be set up.

### Conda

Anemoi-inference requires that the versions are >= those that were used to train the model. Based on the model, the versions below will need to change. For the nested-eagle POC, these versions below should work.

```
conda create --name eagle_nrt python=3.12.12
conda activate eagle_nrt
conda install -c conda-forge ufs2arco
pip install anemoi-datasets==0.5.30 anemoi-graphs==0.8.2 anemoi-models==0.11.3 anemoi-transform==0.1.21 anemoi-utils==0.4.42 anemoi-inference==0.9.1 "torch<2.7" eagle-tools
pip install 'flash-attn<2.8' --no-build-isolation --no-cache-dir
```

### Instructions

nested-eagle regrids the HRRR on the fly to 6km resolution. You will need a static netcdf file to complete this process, which will only need to be done once. In the `config` folder, the `hrrr_6km.py` script will create this file for you. Simply run `python hrrr_6km.py` in your eagle_nrt conda environment. After you have created this file, you can move onto running inference in near-real time.

Next, go into nested_eagle.yaml and update your checkpoint path to wherever you have it stored.

You should now be able to create a forecast!

Step 1: Load initial conditions (CPU)

`python preproc.py --config nested_eagle.yaml`

Step 2: Run inference (GPU)

`python inference.py --config nested_eagle.yaml`
