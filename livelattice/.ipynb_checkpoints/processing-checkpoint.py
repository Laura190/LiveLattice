import numpy as np
from glob import glob
import os
import fnmatch
import time
from tqdm.notebook import trange, tqdm
from tifffile import imread, imwrite
from .helper_func import *
import cupy
import rmm
import dask.array as da
from pycudadecon import *
from dask_image.ndinterp import affine_transform as affine_dask
from cupyx.scipy.ndimage import affine_transform as affine_cupy

# Camera backgrounds
master_bg_ch0 = imread('./camera_background/Master_2304x2304_CamA.tif')
master_bg_ch1 = imread('./camera_background/Master_2304x2304_CamB.tif')

# Parameters
angle=31.708; dzdata=0.3; dxdata=0.111; dzpsf=0.3; dxpsf=0.111; deskew=0; rotate=0; width=0
    
def process_image(image, source, target, psf_path, wavelength, camera_id, save_mip, overwrite_file, use_dask, num_decon_it, decon_zsection_size, do_operations):

    # background subtraction
    image_bg = get_image_background(source, camera_id)
    image_nobg = image - image_bg
    image_nobg[image_nobg >= 2**16-image_bg.max()] = 0
    
    # bleach correction
    if 'stack0000' in source:
        imwrite('./bleach_correct/ref_'+wavelength+'nm.tif', image_nobg)
        image_bleach_corrected = image_nobg
        
    else:
        t1 = time.time()
        
        ref_nobg = imread('./bleach_correct/ref_'+wavelength+'nm.tif')
        mean_current = np.mean(image_nobg[image_nobg>0])
        mean_ref = np.mean(ref_nobg[ref_nobg>0])
        bleach_factor =  mean_ref / mean_current
        image_bleach_corrected = image_nobg * bleach_factor
        print('\nMean intensity at first frame:', mean_ref)
        print('Mean intensity at current frame:', mean_current)
        print('Bleach factor:', bleach_factor)
    
        t2 = time.time()
        print('Bleach correction takes', t2-t1, 'seconds!')

    # PSF background removal
    psf_nobg_path = psf_path[:-4]+'_clean.tif'
    
    if os.path.isfile(psf_nobg_path):
        psf_img_nobg = imread(psf_nobg_path)
        psf_bg = np.mean(np.concatenate([psf_img_nobg[0], psf_img_nobg[-1]])) # estimate remaining psf background

    else:
        psf_img = imread(psf_path)

        mean_psf_bg = np.mean(np.concatenate((psf_img[:5], psf_img[-5:])), axis=0)[np.newaxis]
        
        psf_img_nobg = psf_img.astype('uint16') - mean_psf_bg.astype('uint16') # subtract averaged background    
        
        psf_img_nobg[psf_img_nobg >= 2**16-mean_psf_bg.max()] = 0
    
        psf_nobg_path = psf_path[:-4]+'_clean.tif'
        imwrite(psf_nobg_path, psf_img_nobg)

    do_decon, do_deskewrotate = do_operations
    
    processing = image_bleach_corrected
        
    # Deconvolution
    if do_decon:
        t1 = time.time()

        num_zsections = 0
        if image.shape[0] % decon_zsection_size == 0:
            num_zsections = int(image.shape[0] / decon_zsection_size)
        else:
            num_zsections = int(image.shape[0] / decon_zsection_size) + 1

        pad_size = int(0.1*decon_zsection_size)
        start_z = pad_size
        full_deconv = None

        for ind_z in range(num_zsections):
            
            section = processing[start_z-pad_size:start_z+decon_zsection_size+pad_size]
            if section.shape[0] < pad_size:
                break
                
            print('\nDeconvolution starts for z-section', ind_z+1)
            with TemporaryOTF(psf_nobg_path) as otf:
                with RLContext(section.shape, otf.path, dzdata, dxdata, dzpsf, dxpsf, skewed_decon=True) as ctx:
                
                    section_deconv = rl_decon(section, background=0, n_iters=num_decon_it, skewed_decon=True)

                    # to avoid boundary effect due to partitioning in all x,y,z, we divide only z in blocks for large dataset
                    if start_z == pad_size:
                        full_deconv = section_deconv[:pad_size+decon_zsection_size]
                    else:
                        full_deconv = np.concatenate([full_deconv, section_deconv[pad_size:pad_size+decon_zsection_size]])

                    start_z += decon_zsection_size
                    
        processing = full_deconv.astype('uint16')

        t2 = time.time()
        print('\nDeconvolution takes', t2-t1, 'seconds!')

    # Deskew + Rotation (WH-Transform)
    if do_deskewrotate:

        t1 = time.time()

        if use_dask:
            rmm.reinitialize(managed_memory=True)
            cupy.cuda.set_allocator(rmm.rmm_cupy_allocator)

            processing = cupy.asarray(processing)
            processing = da.from_array(processing)

            # Step 1
            swapped = cupy.swapaxes(processing, 0, 2)
            rotated = cupy.flip(swapped, 2)

            # Step 2
            transformed = scale_and_shear_dask(rotated, angle, dzdata, dxdata)

            # move to CPU memory
            processing = transformed.map_blocks(cupy.asnumpy)
            processing = processing.compute()

        else:
            rmm.reinitialize(managed_memory=True)
            cupy.cuda.set_allocator(rmm.rmm_cupy_allocator)

            processing = cupy.asarray(processing)

            # Step 1
            swapped = cupy.swapaxes(processing, 0, 2)
            rotated = cupy.flip(swapped, 2)

            # Step 2
            transformed = scale_and_shear_cupy(rotated, angle, dzdata, dxdata)

            # move to CPU memory
            processing = cupy.asnumpy(transformed)
            
        t2 = time.time()
        print('\nDeskew and rotation takes', t2-t1, 'seconds!')


    # save MIP
    if save_mip:
        mip_dir = '/'.join([s for s in target.split('/')[:-1]])+'/MIP/'
        mip_name = target.split('/')[-1]
        if not os.path.isdir(mip_dir):
            os.makedirs(mip_dir)
            
        mip = np.max(processing, axis=0)
        try:
            imwrite(mip_dir+mip_name, mip.astype('uint16'))
        except KeyboardInterrupt:
            os.remove(mip_dir+mip_name)

    # save the processed file
    t1 = time.time()
    try:
        final = processing
        imwrite(target, final)
    except:
        os.remove(target)
    t2 = time.time()
    print('\nSize of final volume:', processing.size*processing.itemsize/1E9, 'GB')
    print('\nData write speed:', round((processing.size*processing.itemsize/1E6) / (t2-t1), 2), 'MB/s\n')
    print('File has been processed!\n')
    
    return
    
    
def scale_and_shear_dask(img, angle, dzdata, dxdata):

    # scale
    scale = np.eye(4)
    scale[0,0] = np.sin(angle*cupy.pi/180.0)
    scale[2,2] = dzdata / dxdata

    # shear
    shearfactor = np.cos(angle*np.pi/180.0) / np.sin(angle*np.pi/180.0)
    shear = np.eye(4)
    shear[2,0] = shearfactor

    combined = shear @ scale
    output_shape = get_output_dimensions(combined, img.shape)

    transformed_vol = affine_dask(img, np.linalg.inv(combined), 
                                  output_shape=output_shape, output_chunks=img.chunksize)
    
    return transformed_vol


def scale_and_shear_cupy(img, angle, dzdata, dxdata):

    # scale
    scale = np.eye(4)
    scale[0,0] = np.sin(angle*cupy.pi/180.0)
    scale[2,2] = dzdata / dxdata

    # shear
    shearfactor = np.cos(angle*np.pi/180.0) / np.sin(angle*np.pi/180.0)
    shear = np.eye(4)
    shear[2,0] = shearfactor

    combined = shear @ scale
    output_shape = get_output_dimensions(combined, img.shape)

    transformed_vol = affine_cupy(img, cupy.asarray(np.linalg.inv(combined)), 
                                  output_shape=tuple(output_shape))
    
    return transformed_vol
    

def get_image_background(source, camera_id):
    
    tif_path = '/'.join(source.split('/')[:-1])+'/'
    txt_list = [file for file in os.listdir(tif_path)if fnmatch.fnmatch(file, '*.txt') ]
    settingFileName = ''
    for txtTitle in txt_list:
        if 'Settings' or 'settings' in txtTitle:
            settingFileName = txtTitle

    if len(settingFileName) != 0:

        # Background subtraction
        settingFile = list(open(tif_path+settingFileName,encoding='latin1'))
        roi_line = ''
        for n_line in range(82,109): # usually line number 93 or index 92
            this_line = settingFile[n_line]
            if 'ROI' in this_line:
                roi_line = this_line
                break
        if len(roi_line) == 0:
            raise Exception('Wrong line number does not have ROI.')
            
        line_indices = [i for i in range(len(roi_line)) if roi_line.startswith('=', i)]

        left, top, right, bot = [int(roi_line[i+1:i+5]) for i in line_indices]
    else:
        print('No setting file found for', tif_path)
        print('Use previous camera indices:', left, top, right, bot)
    
    camera_bg = None
    if camera_id == 'CamA':
        camera_bg = master_bg_ch0
    if camera_id == 'CamB':
        camera_bg = master_bg_ch1
        
    bg_roi = camera_bg[top-1:bot, left-1:right]
    rotated_bg_roi = np.rot90(bg_roi, axes=(0,1))

    return rotated_bg_roi


def get_psf_background(source, psf_img, camera_id):
    camera_bg = None
    if camera_id == 'CamA':
        camera_bg = master_bg_ch0
    if camera_id == 'CamB':
        camera_bg = master_bg_ch1
    
    left, top, right, bot = 0, 0, 0, 0
    if psf_img.shape[1] == 64 and psf_img.shape[2] == 64:
        left=1121; top=1121; right=1184; bot=1184
    elif psf_img.shape[1] == 128 and psf_img.shape[2] == 128:
        left=1089; top=1089; right=1216; bot=1216
    else:
        raise Exception('PSF dimensions', psf_img.shape, 'are unexpected!')

    bg_roi = camera_bg[top-1:bot, left-1:right]
    rotated_bg_roi = np.rot90(bg_roi, axes=(0,1))
    return rotated_bg_roi
