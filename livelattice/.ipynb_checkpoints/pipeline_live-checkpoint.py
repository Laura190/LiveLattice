from .processing import *

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
        for channel_tif in sorted(tif_list, reverse=True):
            if next_stack in channel_tif: # if next frame exists
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


def process_data_live(tif_path_list, save_path_list, specified_channels, selected_psf_path, folders_to_process, frames_to_process, save_mip, overwrite_file, use_dask, num_decon_it, decon_zsection_size, decon_deskew_rotate, no_decon, decon_only):
    
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
        frame_interval = None
        
        while True:
            # start processing for the frame that is done acquiring
            if next_frame_exists(tif_path, current_stack_id, total_num_frames):
                stack_number = int_to_stack(current_stack_id)
            
            # compute frame interval
            t0 = os.stat(glob(tif_path+'*stack0000*tif')[0]).st_mtime
            t1 = os.stat(glob(tif_path+'*stack0001*tif')[0]).st_mtime
            frame_interval = round(t1 - t0, 2)
            
            if frames_to_process is not None:
                if current_stack_id not in frames_to_process:
                    current_stack_id += 1
                    continue
            else:
                # get all channels for this frame
                tif_list = [file for file in os.listdir(tif_path)if fnmatch.fnmatch(file, '*.tif')]
                channels_this_frame = [file for file in tif_list if fnmatch.fnmatch(file, '*'+stack_number+'*')]
                if len(channels_this_frame) == 0:
                    continue

                psf_path = None

                for channel_tif in channels_this_frame:

                   # determine the wavelength of current stack
                    wavelength = ''
                    keywords = channel_tif.split('_')
                    if 'CamA' in keywords:
                        offset = keywords.index('CamA')
                    if 'CamB' in keywords:
                        offset = keywords.index('CamB')
                    camera_id = keywords[offset]

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

                        experiment_path = tif_path[:tif_path.index(tif_path.split('/')[-3])] # basically the path to the date level

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

                    # use selected PSF
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
                                continue

                        print('-----------------------------------------------------------------------------------------')
                        print('Wavelength =', wavelength+'nm')
                        print('Frame interval =', str(frame_interval)+'s')
                        print('Frame number =', current_stack_id)
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


                # go to next frame
                current_stack_id += 1
                time.sleep(2)