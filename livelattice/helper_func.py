# The helper functions are adapted from https://github.com/VolkerH/Lattice_Lightsheet_Deskew_Deconv.git
# Credit to Volker Hilsenstein

import numpy as np
from numpy.linalg import inv
from typing import Union, Iterable, Callable, Optional, Collection

def get_transformed_corners(aff, vol_or_shape, zeroindex = True):

    if np.array(vol_or_shape).ndim == 3:
        d0, d1, d2 = np.array(vol_or_shape).shape
    elif np.array(vol_or_shape).ndim == 1:
        d0, d1, d2 = vol_or_shape
    else:
        raise ValueError

    if zeroindex:
        d0 -= 1
        d1 -= 1
        d2 -= 1

    corners_in = [
        (0, 0, 0, 1),
        (d0, 0, 0, 1),
        (0, d1, 0, 1),
        (0, 0, d2, 1),
        (d0, d1, 0, 1),
        (d0, 0, d2, 1),
        (0, d1, d2, 1),
        (d0, d1, d2, 1),
    ]
    corners_out = list(map(lambda c: aff @ np.array(c), corners_in))
    corner_array = np.concatenate(corners_out).reshape((-1, 4))
    
    return corner_array


def ceil_to_mulitple(x, base = 4):
    return (int(base) * np.ceil(np.array(x).astype(float) / base)).astype(int)


def get_output_dimensions(aff, vol_or_shape):

    corners = get_transformed_corners(aff, vol_or_shape, zeroindex=True)
    dims = np.max(corners, axis=0) - np.min(corners, axis=0) + 1
    dims = ceil_to_mulitple(dims, 2)
    return dims[:3].astype(int)


def shift_centre(matrix_shape, direction=-1.0):
    
    assert len(matrix_shape) == 3
    centre = np.array(matrix_shape) / 2
    shift = np.eye(4)
    shift[:3, 3] = direction * centre
    return shift


def unshift_centre(matrix_shape):
    return shift_centre(matrix_shape, 1.0)


def rot_around_y(angle_deg):

    arad = angle_deg * np.pi / 180.0
    roty = np.array(
        [
            [np.cos(arad), 0, np.sin(arad), 0],
            [0, 1, 0, 0],
            [-np.sin(arad), 0, np.cos(arad), 0],
            [0, 0, 0, 1],
        ]
    )
    return roty