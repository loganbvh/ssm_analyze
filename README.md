# Scanning SQUID analysis
`ssm_analyze` is an analysis GUI for scanning SQUID microscopy datasets generated by the [scanning-squid](https://scanning-squid.readthedocs.io/en/latest/) python package.
![scanning-squid-analysis GUI](ssm_analyze/gui/img/screengrab.png)

## Installation

It is recommended to install `ssm_analyze` inside of a dedicated [conda environment](https://conda.io/projects/conda/en/latest/user-guide/tasks/manage-environments.html#creating-an-environment-with-commands). `ssm_analyze` has been tested on Python 3.6, 3.7, 3.8 and 3.9. You can create a [conda environment](https://conda.io/projects/conda/en/latest/user-guide/tasks/manage-environments.html#creating-an-environment-with-commands) using the following commands:

```
conda create --name <env-name> python=<3.6, 3.7, 3.8, or 3.9>
conda activate <env-name>
```

After creating and activating your conda env, you can install `ssm-analyze` in one of two ways:

### Install via [pip](https://pypi.org/project/ssm-analyze/)
```
pip install ssm-analyze
```

### Install from source
- [Clone](https://help.github.com/en/articles/cloning-a-repository) or download [this repository](https://github.com/loganbvh/ssm_analyze)
- Navigate to this directory and install `ssm_analyze` using `pip`:
  ```
  pip install -e .
  ```

## Usage
- Start the GUI by running either of the below commands from the command line:
  ```
  ssm_analyze
  ```
  or
  ```
  python -m ssm_analyze.start_gui
  ```
- Use the **Select directory** button, *File -> Select directory...*, or ctrl+O (Windows)/cmd+O (Mac) to select the data directory. This base directory (for example `sample_data/data` in this repo) should contain dated subdirectories, which in turn contain single datasets (e.g. `sample_data/data/2018-09-14/#016_scan_13-07-41`).
- Click a specific dataset in the **DataSet Browser** to load its data. The dataset metadata and instrument settings can be examined with the **Measurement Metadata** and **Microscope Snapshot** widgets.
- The arrays contained in the dataset can be visualized/lightly processed in the **DataSet Plotter**.
- The current matplotlib figure can be exported using *Plot -> Export matplotlib...* or ctrl+P (Windows)/cmd+P (Mac).
- The currently displayed data (including any rotations, background subtraction, cross-sections, etc.) can be exported using *File -> Export current data...* or ctrl+S (Windows)/cmd+S (Mac). The available export formats are:
  - MATLAB .mat file: Each array is saved to a struct with field names 'array' and 'unit'.
  - HDF5 .h5 file: Can be read by [h5py](https://www.h5py.org/), [MATLAB](https://www.mathworks.com/help/matlab/ref/hdf5read.html), or viewed with [HDF5 View](https://www.hdfgroup.org/downloads/hdfview/).
  - Python pickle: A dictionary of arrays is written directly to a file in binary form and can be loaded using:
    ```python
    import pickle
    with open('filename.pickle', 'rb') as f:
        arrays = pickle.load(f)
    ```
- The built-in IPython console has access to the following:
  - matplotlib.pyplot: `plt`
  - numpy: `np`
  - a dict of the current arrays in the form of arrays of [pint](https://pint.readthedocs.io/en/latest/) `Quantities`. For example, `arrays['MAG'].magnitude` will be the `MAG` array, with units `arrays['MAG'].units`
  - the current `qcodes.data.data_set.DataSet`: `dataset`

## Notes
- If you wish to uninstall the program, run `conda remove -n <env-name> --all` to remove the conda environment, then delete this repository.
- If you find bugs/have suggestions for new features, please use the [GitHub Issues feature](https://github.com/loganbvh/scanning-squid-analysis/issues).
- Contact: logan.bvh@gmail.com.
- Logo by [Tom Shahar](http://www.tomshahar.io/).
