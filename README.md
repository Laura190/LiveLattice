# LiveLattice: Live Visualization of Lattice Lightsheet Dataset
**LiveLattice** is a Python-based pipeline for preprocessing and live/real-time visualization of 4D (x,y,z,time) lattice light-sheet datasets while data is streaming from the scope.

LiveLattice is conceived by Hiroyuki Hakozaki (hhakozaki@health.ucsd.edu) and Zichen (Zachary) Wang (ziw056@ucsd.edu), and is written by Zachary Wang with the help from people in the [Johannes Schöneberg lab](https://www.schoeneberglab.org/) at UCSD.

It uses cudaDecon for deconvolution (optional), and Napari for interactive visualization.  

# Installation
Clone this [repository](https://github.com/pylattice/LiveLattice).

### Python dependencies
Currently, LiveLattice has only been tested on Linux.
We will create a conda environment that automatically installs all the required dependencies.  
1. Go to the root directory of this repository  
2. Create the enviroment using the provided .yml file: `conda env create -f setup_linux_env.yml`  

To use LiveLattice, first activate the environmnet we created with `conda activate livelattice`, and then open notebook with `jupyter notebook`.

# Example data folder structure
<pre>
Experiment Name
    - PSF
        - Hex
            - XStage_488nm
            - XStage_560nm
            - XStage_642nm
    - Sample 1
        - Location 1
            - All .tif files
            - Setting file
        - Location 2
            - All .tif files
            - Setting file
    - Sample 2
        - Location 1
            - All .tif files
            - Setting file
        - Location 2
            - All .tif files
            - Setting file
</pre>

# Pre-processing routine
**Pre-process multi-channel 4D dataset that has been acquired.**

### MOSAIC_Preprocessing_Only.ipynb

#### 1. Select the data folders to process
Specify the number of folders you want to process in `number_of_folders`.  
After running the block, a window will pop up for you to select the date. Make sure click “Choose”. Double click will enter the folder instead.
If you need to process more than one date, more windows will pop up as needed. All data subfolders will be automatically detected and display. Check if they are correct.  
In cases where the automatic determination of wavelength failed, input the wavelength manually in the order of file name sorting. For example, `specified_channels=['488', '642']` can be used if the first channel is 488nm and second 642 nm.  
In cases where you want to manually specify the PSF files instead of automatic detection based on the wavelength, spcify the path to each file as a list in `selected_psf_path`.  
**Currently, we only support automatic detection using the setting files and file naming convention same as our lattice lightsheet microscope.**  

#### 2. Set parameters and process the movies
`folders_to_process`: the folders selected from the list displayed in Step 2. Use 'None' for all folders. Otherwise input a list of index numbers (int) for the selected folders. Index starts at 0.  
`frames_to_process`: the frames/timepoints selected. Use 'None' for all frames. Otherwise input a list of index numbers (int) for the selected folders. Index starts at 0.  
`save_MIP`: whether to create maximum intensity projection images.  
`overwrite_file`: whether to overwrite existing files. Set to False if you want to continue previous run.   
Note: when resume a previous run, bleach correction will be performed using the first frame files under bleach_correct folder in order to speed things up. Make sure this is the correct file for current folder.  
`use_dask`: whether to use dask for pre-processing. Only needed for dataset/hardware where memory overflow is encountered.  
`num_decon_it`: number of iterations in richardson-lucy deconvolution  
`skewed_decon`: if True, deconvolution is performed on the raw data using sample scan PSF; if False, deconvolution is performed on the deskewed and rotated data using detective objective PSF.  
`decon_zsection_size`: For larger dataset, deconvolution is performed on overlapping z-sections consecutively. Depending on the data size and whether skewed deconvolution is used, you may need to adjust the size until the deconvolution can be performed in reasonable time.  
`decon_deskew_rotate`: perform all three operations. This is the usual case.  
`no_decon`: only perform deskew and rotate. This can be used for visualization where deconvolution is not required.  
decon_only: only perform skewed deconvolution. This is for test purposes.  
After specifying all paramters, run `process_data()` and the data will be processed and progress updates will be displayed.  

# Live visualization routine
**The live visualization routine is based on the pre-processing routine but can dynamically load newly acquired data into pre-processing routine and visualize the results in Napari.**

### MOSAIC_Live_Visualization_Preprocessing.ipynb
Run this jupyter notebook on the folder to which the data to be aquired will be saved. The usage is the same as the pre-processing routine detailed above. `process_data_live()` will process the new data saved to the chosen folder as it is produced from the microsscope in real-time. Please manually close it after the experiment is complete.

### MOSAIC_Live_Visualization_Napari.ipynb
Run this jupyter notebook on the folder to which the data to be aquired will be saved. Any pre-processed data will be loaded into Napari and organized by channel/timepoint.  
`use_dask_for_napari`: whether to use dask for loading the data into Napari. This is needed if the 4D dataset is larger than memory.
