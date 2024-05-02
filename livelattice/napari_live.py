import numpy as np
from glob import glob
import os
import fnmatch
import time
from tqdm.notebook import trange, tqdm
from tifffile import imread, imwrite
import napari
from napari.qt.threading import thread_worker
import dask.array as da
from dask.array.image import imread as dask_imread

def int_to_stack(frame_index):

    if len(str(frame_index)) == 1:
        return 'stack000'+str(frame_index)
    elif len(str(frame_index)) == 2:
        return 'stack00'+str(frame_index)
    elif len(str(frame_index)) == 3:
        return 'stack0'+str(frame_index)
    else:
        raise Exception('Integer input is needed!')
                    
            
def next_frame_exists(tif_path, current_stack_id, total_num_frames):

    while True:
        tif_list = [file for file in os.listdir(tif_path)if fnmatch.fnmatch(file, '*.tif')]
        next_stack = int_to_stack(current_stack_id+1)
        
        if current_stack_id == total_num_frames - 1:
            return True
        
        # check if next frame exists
        for tif_name in sorted(tif_list, reverse=True):
            if next_stack in tif_name: # if next frame exists
                return True
            
        time.sleep(2)
        
    
def collect_data_locations(root_path, all_data_path, output_path):
    
    tif_path_list =[]
    save_path_list = []
    
    # loop all dates
    for data_path in all_data_path:
        if not os.path.isdir(output_path+data_path):
            os.makedirs(output_path+data_path)

        # loop all samples
        for sample_folder_name in sorted(os.listdir(root_path+data_path)):

            if 'Sample' in sample_folder_name or 'sample' in sample_folder_name:

                sample_folder_path = root_path+data_path+'/'+sample_folder_name+'/'
                new_sample_folder_path = output_path+data_path+'/'+sample_folder_name+'/'

                if not os.path.isdir(sample_folder_path):
                    continue
                if not os.path.isdir(new_sample_folder_path):
                    os.mkdir(new_sample_folder_path)

                # loop all locations
                for region_folder_name in sorted(os.listdir(sample_folder_path)):

                    region_folder_path = sample_folder_path+region_folder_name+'/'
                    new_region_folder_path = output_path+data_path+'/'+sample_folder_name+'/'+region_folder_name+'/'

                    if not os.path.isdir(region_folder_path):
                        continue
                    if not os.path.isdir(new_region_folder_path):
                        os.mkdir(new_region_folder_path)

                    tif_path_list.append(region_folder_path)
                    save_path_list.append(new_region_folder_path)

                    # check for any nesting directory due to treatments
                    contents = os.listdir(region_folder_path)
                    if len(contents) < 6: # assuming there are less than 6 conditions possible, otherwise it costs time to run
                        nesting_dirs = [d for d in contents if os.path.isdir(region_folder_path+d)]
                        for d in nesting_dirs:
                            tif_path_list.append(region_folder_path+d+'/')
                            save_path_list.append(new_region_folder_path+d+'/')

    print('The following directories are present in the folders you selected:\n')
    for i,p in enumerate(tif_path_list):
        print('\nFolder '+str(i)+':')
        print(p)
        
    return tif_path_list, save_path_list


def napari_live(args):
    viewer, save_path, stack_number, use_dask_for_napari, first = args

    if use_dask_for_napari:
        current_all_channels = dask_imread(save_path+'*'+stack_number+'*tif')

        if first:
            first_stack = np.swapaxes(current_all_channels.reshape((1,)+current_all_channels.shape), 0, 1)
            viewer.add_image(first_stack, channel_axis=0, name=['channel '+str(n) for n in range(len(current_all_channels))])
        else:
            for channel_id in range(len(current_all_channels)):
                layer = viewer.layers[channel_id]
                new_data = current_all_channels[channel_id]
                layer.data = da.concatenate([layer.data, new_data.reshape((1,)+new_data.shape)], axis=0)

    else:
        current_all_channels = np.array([imread(tif) for tif in sorted(glob(save_path+'*'+stack_number+'*tif'))])

        if first:
            first_stack = np.swapaxes(current_all_channels.reshape((1,)+current_all_channels.shape), 0, 1)
            viewer.add_image(first_stack, channel_axis=0, name=['channel '+str(n) for n in range(len(current_all_channels))])
        else:
            for channel_id in range(len(current_all_channels)):
                layer = viewer.layers[channel_id]
                new_data = current_all_channels[channel_id]
                layer.data = np.concatenate([layer.data, new_data.reshape((1,)+new_data.shape)], axis=0)
        
            
@thread_worker(connect={'yielded': napari_live})
def visualize_data_live(viewer, tif_path_list, save_path_list,
                        folders_to_process, frames_to_process,
                        use_dask_for_napari,
                        decon_deskew_rotate, no_decon, decon_only):
    
    operation_list = []
    if decon_deskew_rotate:
        operation_list.append([True, True]) # in order of decon, deskew and rotate
    if no_decon:
        operation_list.append([False, True]) # in order of decon, deskew and rotate
    if decon_only:
        operation_list.append([True, False]) # in order of decon, deskew and rotate
        
    if folders_to_process is None:
        folders_to_process = range(len(tif_path_list))

    print('The following selected folders will be processed:')
    for i,p in enumerate([tif_path_list[i] for i in folders_to_process]):
        print('\nFolder '+str(i)+':')
        print(p)
        
    for path_index in folders_to_process:
        
        tif_path = tif_path_list[path_index]
        save_path = save_path_list[path_index]

        setting_exists = False
        while not setting_exists:
            txt_list = [file for file in os.listdir(tif_path)if fnmatch.fnmatch(file, '*.txt')]
            settingFileName = ''
            for txtTitle in txt_list:
                if 'Settings' in txtTitle:
                    settingFileName = txtTitle
                    setting_exists = True
            if setting_exists:
                break
            else:
                time.sleep(2)
                            
        settingFile = list(open(tif_path+settingFileName, encoding='latin1'))
        
        # determine total number of frames
        total_num_frames = None
        for l in range(35,55):
            if '# of stacks' in settingFile[l].split('\t')[0]:
                total_num_frames = int(settingFile[l].split('\t')[1])
                print('\nTotal number of frames in this movie:', total_num_frames, '\n')
                break
        if total_num_frames is None:
            raise Exception('Failed to determine the total number of frames!')
            
        # find and process files for each frame dynamically as data is being acquired
        current_stack_id = 0
        first = True
        
        if frames_to_process is not None:
            
            for stack_id in frames_to_process:
                
                stack_number = int_to_stack(stack_id)

                tif_list = [file for file in os.listdir(save_path)if fnmatch.fnmatch(file, '*.tif')]
                tif_this_frame = [file for file in tif_list if fnmatch.fnmatch(file, '*'+stack_number+'*')]
                if len(tif_this_frame) == 0:
                    continue
                    
                for tif_name in tif_this_frame:
                    print('Images loaded in napari:', tif_name)

                args = (viewer, save_path, stack_number, use_dask_for_napari, first)
                yield args # pass to napari_live()
                first = False
                
        else:
            while True:
                # start processing for the frame that is done acquiring
                if next_frame_exists(save_path, current_stack_id, total_num_frames):
                    stack_number = int_to_stack(current_stack_id)

                tif_list = [file for file in os.listdir(save_path)if fnmatch.fnmatch(file, '*.tif')]
                tif_this_frame = [file for file in tif_list if fnmatch.fnmatch(file, '*'+stack_number+'*')]
                if len(tif_this_frame) == 0:
                    continue

                for tif_name in tif_this_frame:
                    print('Images loaded in napari:', tif_name)

                args = (viewer, save_path, stack_number, use_dask_for_napari, first)
                yield args # pass to napari_live()
                first = False

                if current_stack_id == total_num_frames - 1: # end of movie
                    return

                current_stack_id += 1

                time.sleep(2)