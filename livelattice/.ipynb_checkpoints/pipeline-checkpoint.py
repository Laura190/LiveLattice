from .processing import *

def collect_data_locations(root_path, all_data_path, output_path):
    
    tif_path_list =[]
    save_path_list = []
    
    # loop all dates
    for data_path in all_data_path:
        if not os.path.isdir(output_path+data_path):
            os.makedirs(output_path+data_path)

        # loop all samples
        for sample_folder_name in sorted(os.listdir(root_path+data_path)):

            if 'Sample' in sample_folder_name:

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
                    if len(contents) < 5: # assuming there are less than 6 conditions possible, otherwise it costs time to run
                        nesting_dirs = [d for d in contents if os.path.isdir(region_folder_path+d)]
                        for d in nesting_dirs:
                            tif_path_list.append(region_folder_path+d+'/')
                            save_path_list.append(new_region_folder_path+d+'/')

    print('The following directories are present in the folders you selected:\n')
    for i,p in enumerate(tif_path_list):
        print('\nFolder '+str(i)+':')
        print(p)
        
    return tif_path_list, save_path_list
    
    
def combine_mip(count, tif_list, suffix, save_path):
    
    try:
        # combine all MIPs into a single tif
        if count == len(tif_list): # only if current run uses all the files
            mip_dir = save_path+'MIP/'

            tif_list_488 = sorted([mip_dir+file for file in os.listdir(mip_dir)if fnmatch.fnmatch(file, '*488nm*'+suffix+'*')])
            tif_list_560 = sorted([mip_dir+file for file in os.listdir(mip_dir)if fnmatch.fnmatch(file, '*560nm*'+suffix+'*')])
            tif_list_642 = sorted([mip_dir+file for file in os.listdir(mip_dir)if fnmatch.fnmatch(file, '*642nm*'+suffix+'*')])

            numpy_list_488 = np.array([imread(tif) for tif in tif_list_488])
            numpy_list_560 = np.array([imread(tif) for tif in tif_list_560])
            numpy_list_642 = np.array([imread(tif) for tif in tif_list_642])

            all_channels = [numpy_list_488, numpy_list_560, numpy_list_642]
            valid_channels = [c for c in all_channels if len(c) > 0]

            if len(valid_channels) >= 2:
                combined_ctyx = np.array(valid_channels)
                combined_tcyx = np.swapaxes(combined_ctyx, 0, 1)
                combined_tzcyx = combined_tcyx[:, np.newaxis] # ImageJ uses TZCYX order

            elif len(valid_channels) == 1:
                combined_tzcyx = valid_channels[0][:, np.newaxis, np.newaxis]

            imwrite(mip_dir+'MIP_'+suffix+'_combined.tif', combined_tzcyx, imagej=True)
            print('Combined MIP movie is saved!')
    except:
        print('Failed to combined all MIPs into single stack!')
        
    else:
        return
    
def process_data(tif_path_list, save_path_list, specified_channels, selected_psf_path, folders_to_process, frames_to_process, save_mip, overwrite_file, use_dask, num_decon_it, decon_zsection_size, decon_deskew_rotate, no_decon, decon_only):
    
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
    
    for path_index in tqdm(folders_to_process):
                
        tif_path = tif_path_list[path_index]
        tif_list = [file for file in os.listdir(tif_path)if fnmatch.fnmatch(file, '*.tif')]
        if len(tif_list) == 0:
            continue
        
        # check for imcomplete stacks
        file_size_list = []
        for frame_index in range(0, len(tif_list)):
            offset = 0
            tif_name = tif_list[frame_index]
            
            # collect file size
            file_stats = os.stat(tif_path+tif_name)
            file_size_list.append(round(file_stats.st_size/1E9, 1))

        if len(np.unique(file_size_list)) != 1:
            for f in file_size_list:
                print(f, 'GB')
            error = 'The file sizes are not the same in '+tif_path+'. Please check for imcomplete files.'
            raise Exception(error)

        # determine the channels used
        txt_list = [file for file in os.listdir(tif_path)if fnmatch.fnmatch(file, '*.txt')]
        settingFileName = ''
        for txtTitle in txt_list:
            if 'Settings' in txtTitle:
                settingFileName = txtTitle
        if len(settingFileName) == '':
            raise Exception('Setting file not found!')
                            
        settingFile = list(open(tif_path+settingFileName, encoding='latin1'))
        seq1_wave1, seq1_wave2, seq2_wave1, seq2_wave2 = 'OFF', 'OFF', 'OFF', 'OFF'
        for l in range(40,60):
            if settingFile[l].split('\t')[0]=='Excitation Filter, Laser, Power (%), Exp(ms), Laser2, Power2 (%), Laser3, Power3 (%) (0) :':
                seq1_wave1, seq1_wave2 = settingFile[l].split('\t')[2], settingFile[l].split('\t')[5]
            if settingFile[l].split('\t')[0]=='Excitation Filter, Laser, Power (%), Exp(ms), Laser2, Power2 (%), Laser3, Power3 (%) (1) :':
                seq2_wave1, seq2_wave2 = settingFile[l].split('\t')[2], settingFile[l].split('\t')[5]

        all_waves = [wave for wave in [seq1_wave1, seq1_wave2, seq2_wave1, seq2_wave2] if wave != 'OFF']

        # find and process files for each channel one frame at a time
        count = 0
        print('\nProgress for selected frames in current folder:')
        
        frames_to_process_current = frames_to_process
        if frames_to_process is None:
            frames_to_process_current = range(int(len(tif_list)/len(all_waves)))
        
        for frame_index in tqdm(frames_to_process_current):
            
            stack_number = ''
            # if use iteration for indexing please change the name
            if len(str(frame_index)) == 1:
                stack_number = 'stack000'+str(frame_index)
            if len(str(frame_index)) == 2:
                stack_number = 'stack00'+str(frame_index)
            if len(str(frame_index)) == 3:
                stack_number = 'stack0'+str(frame_index)
                
            channels_this_frame = [file for file in tif_list if fnmatch.fnmatch(file, '*'+stack_number+'*')]
            if len(channels_this_frame) == 0:
                continue

            psf_path = None

            for channel_id, channel_tif in enumerate(channels_this_frame):

                count += 1
                wavelength = ''
                
                keywords = channel_tif.split('_')
                if 'CamA' in keywords:
                    offset = keywords.index('CamA')
                if 'CamB' in keywords:
                    offset = keywords.index('CamB')
                camera_id = keywords[offset]

                # determine the wavelength based on manual inputs
                if specified_channels is not None:
                    wavelength = specified_channels[channel_id]

                    try:
                        int(wavelength)
                    except:
                        raise Exeption('Invalid wavelength input! Please input the 3-digit wavelength number as a string.')

                # determine the wavelength of current stack automatically
                else:
                    if camera_id == 'CamA':
                        if seq1_wave1+'nm' in channel_tif:
                            wavelength = seq1_wave1
                        elif seq2_wave1+'nm' in channel_tif:
                            wavelength = seq2_wave1
                            
                    if camera_id == 'CamB':
                        if seq1_wave1+'nm' in channel_tif:
                            if int(seq1_wave1) >= 560:
                                wavelength = seq1_wave1
                            else:
                                wavelength = seq1_wave2
                        elif seq2_wave1+'nm' in channel_tif:
                            if int(seq2_wave1) >= 560:
                                wavelength = seq2_wave1
                            else:
                                wavelength = seq2_wave2

                    if wavelength == '' or wavelength == 'OFF':
                        raise Exception('Wavelength failed to be determined!')
                    
                # check which PSF to use based on the type of lightsheet                
                type_sheet = ''
                for l in range(110,150):
                    this_line = settingFile[l]
                    if this_line[:3] == wavelength:
                        type_sheet = this_line.split('\t')[1]
                        break
                if type_sheet == '':
                    raise Exception('Type of lightsheet failed to be determined!')
                    
                # auto-detect PSF file path
                if selected_psf_path is None:
                    
                    experiment_path = tif_path[:tif_path.index('Sample')] # basically the path to the date level
                    
                    if type_sheet == 'Hex':
                        try:
                            psf_path = glob(experiment_path+'PSF/*Hex*/*XStage_'+wavelength+'*/*tif')[0]
                        except:
                            raise Exception('PSF not found for "'+experiment_path+'". Please check for any typos.')
                                
                    elif type_sheet == 'N Bessel':
                        try:
                            psf_path = glob(experiment_path+'PSF/*NB*/*XStage_'+wavelength+'*/*tif')[0]
                        except:
                            raise Exception('PSF not found for "'+experiment_path+'". Please check for any typos.')
                
                else:
                    psf_path_488, psf_path_560, psf_path_642 = selected_psf_path
    
                    if wavelength == '488':
                        psf_path = psf_path_488
    
                    if wavelength == '560':
                        psf_path = psf_path_560
    
                    if wavelength == '642':
                        psf_path = psf_path_642
                
                # start the prcessing
                for do_operations in operation_list:

                    suffix = ''
                    if do_operations == [True, True]:
                        suffix = 'processed'
                    elif do_operations == [False, True]:
                        suffix = 'noDecon'
                    elif do_operations == [True, False]:
                        suffix = 'deconOnly'
                    else:
                        raise Exception('Error')

                    save_name = '_'.join(keywords[0:offset])+'_'+wavelength+'nm_'+keywords[3+offset]+'_'+keywords[5+offset]+'_'+suffix+'.tif'
            
                    save_path = save_path_list[path_index]

                    if not os.path.isdir(save_path):
                        os.makedirs(save_path)

                    if not overwrite_file:
                        if os.path.isfile(save_path+save_name):
                            print(channel_tif, 'is already processed.\n')
                            if save_mip:
                                combine_mip(count, tif_list, suffix, save_path)
                            continue

                    print('-----------------------------------------------------------------------------------------')
                    print('Wavelength =', wavelength+'nm')
                    print('Frame number =', frame_index)
                    print('\nCurrent PSF directory:\n', psf_path, '\n')
                    print('Current image directory:\n', tif_path+channel_tif, '\n')
                    print('Current processed image directory:\n', save_path+save_name)
                    
                    # see if each timepoint is split into 2 .tif files
                    if 'part_0001' in channel_tif:
                        continue

                    second_channel_tif = channel_tif.split('.')[0]+'_part0001.tif'
                    if os.path.isfile(tif_path+second_channel_tif):
                        t1 = time.time()
                        image1 = imread(tif_path+channel_tif)
                        image2 = imread(tif_path+second_channel_tif)
                        image = np.concatenate([image1, image2])
                        t2 = time.time()
                        print('\nData read speed:', round((image.size*image.itemsize/10**6) / (t2-t1), 2), 'MB/s')
                    else:
                        t1 = time.time()
                        image = imread(tif_path+channel_tif)
                        t2 = time.time()
                        print('\nData read speed:', round((image.size*image.itemsize/10**6) / (t2-t1), 2), 'MB/s')
                    
                    print('\nData dimensions are:', image.shape)
                    
                    # process the volume
                    process_image(image,
                                  tif_path+channel_tif,
                                  save_path+save_name,
                                  psf_path,
                                  wavelength,
                                  camera_id,
                                  save_mip,
                                  overwrite_file,
                                  use_dask,
                                  num_decon_it, 
                                  decon_zsection_size,
                                  do_operations)


                    # combine all MIPs into a single tif
                    if save_mip:
                        combine_mip(count, tif_list, suffix, save_path)
