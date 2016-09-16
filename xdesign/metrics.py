#!/usr/bin/env python
# -*- coding: utf-8 -*-

# #########################################################################
# Copyright (c) 2016, UChicago Argonne, LLC. All rights reserved.         #
#                                                                         #
# Copyright 2016. UChicago Argonne, LLC. This software was produced       #
# under U.S. Government contract DE-AC02-06CH11357 for Argonne National   #
# Laboratory (ANL), which is operated by UChicago Argonne, LLC for the    #
# U.S. Department of Energy. The U.S. Government has rights to use,       #
# reproduce, and distribute this software.  NEITHER THE GOVERNMENT NOR    #
# UChicago Argonne, LLC MAKES ANY WARRANTY, EXPRESS OR IMPLIED, OR        #
# ASSUMES ANY LIABILITY FOR THE USE OF THIS SOFTWARE.  If software is     #
# modified to produce derivative works, such modified software should     #
# be clearly marked, so as not to confuse it with the version available   #
# from ANL.                                                               #
#                                                                         #
# Additionally, redistribution and use in source and binary forms, with   #
# or without modification, are permitted provided that the following      #
# conditions are met:                                                     #
#                                                                         #
#     * Redistributions of source code must retain the above copyright    #
#       notice, this list of conditions and the following disclaimer.     #
#                                                                         #
#     * Redistributions in binary form must reproduce the above copyright #
#       notice, this list of conditions and the following disclaimer in   #
#       the documentation and/or other materials provided with the        #
#       distribution.                                                     #
#                                                                         #
#     * Neither the name of UChicago Argonne, LLC, Argonne National       #
#       Laboratory, ANL, the U.S. Government, nor the names of its        #
#       contributors may be used to endorse or promote products derived   #
#       from this software without specific prior written permission.     #
#                                                                         #
# THIS SOFTWARE IS PROVIDED BY UChicago Argonne, LLC AND CONTRIBUTORS     #
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT       #
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS       #
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL UChicago     #
# Argonne, LLC OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,        #
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,    #
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;        #
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER        #
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT      #
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN       #
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE         #
# POSSIBILITY OF SUCH DAMAGE.                                             #
# #########################################################################

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

from xdesign.material import HyperbolicConcentric
from xdesign.material import UnitCircle

import scipy.ndimage
import logging
import warnings
import itertools
import numpy as np
import matplotlib.pyplot as plt

from scipy.stats import norm, exponnorm, expon, ttest_ind
#from phasepack import phasecongmono as _phasecongmono

logger = logging.getLogger(__name__)

__author__ = "Daniel Ching, Doga Gursoy"
__copyright__ = "Copyright (c) 2016, UChicago Argonne, LLC."
__docformat__ = 'restructuredtext en'
__all__ = ['ImageQuality',
           'probability_mask',
           'compute_quality',
           'compute_PCC',
           'compute_likeness',
           'compute_background_ttest',
           'compute_mtf',
           'compute_nps',
           'compute_neq']


def compute_mtf2(phantom, image):
    """Approximates the modulation tranfer function using the
    HyperbolicCocentric phantom. Calculates the MTF from the modulation depth
    at each edge on the line from (0.5,0.5) to (0.5,1). MTF = (hi-lo)/(hi+lo)

    This method rapidly becomes inaccurate at small wavelenths because the
    measurement gets out of phase with the waves due to rounding error. It
    should be replaced with a method that fits a decaying damped cylindrical
    sine function.

    Parameters
    ---------------
    phantom : HyperbolicConcentric
        Predefined phantom of cocentric rings whose widths decay parabolically.
    image : ndarray
        The reconstruction of the above phantom.

    Returns
    --------------
    wavelength : list
        wavelenth in the scale of the original phantom
    MTF : list
        MTF values
    """
    if not isinstance(phantom, HyperbolicConcentric):
        raise TypeError

    center = int(image.shape[0] / 2)  # assume square shape
    radii = np.array(phantom.radii) * image.shape[0]
    widths = np.array(phantom.widths) * image.shape[0]

    # plt.figure()
    # plt.plot(image[int(center),:])
    # plt.show(block=True)

    MTF = []
    for i in range(1, len(widths) - 1):
        # Locate the edge between rings in the discrete reconstruction.
        mid = int(center + radii[i])  # middle of edge
        rig = int(mid + widths[i + 1])  # right boundary
        lef = int(mid - widths[i + 1])  # left boundary
        # print(lef,mid,rig)

        # Stop when the waves are below the size of a pixel
        if rig == mid or lef == mid:
            break

        # Calculate MTF at the edge
        hi = np.sum(image[center, lef:mid])
        lo = np.sum(image[center, mid:rig])
        MTF.append(abs(hi - lo) / (hi + lo))

        # plt.figure()
        # plt.plot(image[int(center),int(lef):int(rig)])
        # plt.show(block=True)

    wavelength = phantom.widths[1:-1]
    return wavelength, MTF


def compute_mtf(phantom, image, Ntheta=4):
    '''Uses method described in Friedman et al to calculate the MTF.

    Parameters
    ---------------
    phantom : UnitCircle
        Predefined phantom with single circle whose radius is less than 0.5.
    image : ndarray
        The reconstruction of the above phantom.
    Ntheta : scalar
        The number of directions at which to calculate the MTF.

    Returns
    --------------
    wavenumber : ndarray
        wavelenth in the scale of the original phantom
    MTF : ndarray
        MTF values

    References
    ---------------
    S. N. Friedman, G. S. K. Fung, J. H. Siewerdsen, and B. M. W. Tsui.  "A
    simple approach to measure computed tomography (CT) modulation transfer
    function (MTF) and noise-power spectrum (NPS) using the American College
    of Radiology (ACR) accreditation phantom," Med. Phys. 40, 051907-1 -
    051907-9 (2013). http://dx.doi.org/10.1118/1.4800795
    '''
    if not isinstance(phantom, UnitCircle):
        raise TypeError('MTF requires unit circle phantom.')
    if phantom.feature[0].radius >= 0.5:
        raise ValueError('Radius of the phantom should be less than 0.5.')
    if Ntheta <= 0:
        raise ValueError('Must calculate MTF in at least one direction.')
    if not isinstance(image, np.ndarray):
        raise TypeError('image must be numpy.ndarray')

    # convert pixel coordinates to length coordinates
    x = y = (np.arange(0, image.shape[0]) / image.shape[0] - 0.5)
    X, Y = np.meshgrid(x, y)
    # calculate polar coordinates for each position
    R = np.sqrt(X**2 + Y**2)
    Th = np.arctan2(Y, X)
    # print(x)

    # Normalize the data to [0,1)
    x_circle = np.mean(image[R < phantom.feature[0].radius - 0.01])
    x_air = np.mean(image[R > phantom.feature[0].radius + 0.01])
    # print(x_air)
    # print(x_circle)
    image = (image - x_air) / (x_circle - x_air)
    image[image < 0] = 0
    image[image > 1] = 1

    # [length] (R is already converted to length)
    R_bin_width = 1 / image.shape[0]
    R_bins = np.arange(0, np.max(R), R_bin_width)
    # print(R_bins)

    Th_bin_width = 2 * np.pi / Ntheta  # [radians]
    Th_bins = np.arange(-Th_bin_width / 2, 2 * np.pi -
                        Th_bin_width / 2, Th_bin_width)
    Th[Th < -Th_bin_width / 2] = 2 * np.pi + Th[Th < -Th_bin_width / 2]
    # print(Th_bins)

    # data with radius falling within a given bin are averaged together for a
    # low noise approximation of the ESF at the given radius
    ESF = np.empty([Th_bins.size, R_bins.size])
    ESF[:] = np.NAN
    count = np.zeros([Th_bins.size, R_bins.size])
    for r in range(0, R_bins.size):
        Rmask = R_bins[r] <= R
        if r + 1 < R_bins.size:
            Rmask = np.bitwise_and(Rmask, R < R_bins[r + 1])

        for th in range(0, Th_bins.size):
            Tmask = Th_bins[th] <= Th
            if th + 1 < Th_bins.size:
                Tmask = np.bitwise_and(Tmask, Th < Th_bins[th + 1])

            # average all the counts for equal radii
            # TODO: Determine whether count is actually needed. It could be
            # replaced with np.mean
            mask = np.bitwise_and(Tmask, Rmask)
            count[th, r] = np.sum(mask)
            if 0 < count[th, r]:  # some bins may be empty
                ESF[th, r] = np.sum(image[mask]) / count[th, r]

    while np.sum(np.isnan(ESF)):  # smooth over empty bins
        ESF[np.isnan(ESF)] = ESF[np.roll(np.isnan(ESF), -1)]

    # plt.figure()
    # for i in range(0,ESF.shape[0]):
    #    plt.plot(ESF[i,:])
    # plt.xlabel('radius');
    # plt.title('ESF')

    LSF = -np.diff(ESF, axis=1)

    # trim the LSF so that the edge is in the center of the data
    edge_center = int(phantom.feature[0].radius / R_bin_width)
    # print(edge_center)
    pad = int(LSF.shape[1] / 5)
    LSF = LSF[:, edge_center - pad:edge_center + pad + 1]
    # print(LSF)
    LSF_weighted = LSF * np.hanning(LSF.shape[1])

    # plt.figure()
    # for i in range(0,LSF.shape[0]):
    #    plt.plot(LSF[i,:])
    # plt.xlabel('radius');
    # plt.title('LSF')
    # plt.show(block=True)

    # Calculate the MTF
    T = np.fft.fftshift(np.fft.fft(LSF_weighted))
    faxis = (np.arange(0, LSF.shape[1]) / LSF.shape[1] - 0.5) / R_bin_width
    nyquist = 0.5*image.shape[0]

    MTF = np.abs(T)
    # Plot the MTF
    plt.figure()
    m = itertools.cycle(('+', ',', 'o', '.', '*'))
    for i in range(0, MTF.shape[0]):
        plt.plot(faxis, MTF[i, :], marker=next(m))
    plt.axvline(nyquist)
    plt.xlabel('spatial frequency [cycles/length]')
    plt.ylabel('Radial MTF')
    plt.axis([0, nyquist, 0, 1])
    a = (Th_bins + Th_bin_width/2)/np.pi
    plt.legend([str(n) + '$\pi$' for n in a])
    plt.title("Modulation Tansfer Function for various angles")
    # plt.show(block=True)
    return faxis, MTF


def compute_nps(phantom, A, B=None, plot_type='frequency'):
    '''Calculates the noise power spectrum from a unit circle image. The peak
    at low spatial frequency is probably due to aliasing. Invesigation into
    supressing this peak is necessary.

    References
    ---------------
    S. N. Friedman, G. S. K. Fung, J. H. Siewerdsen, and B. M. W. Tsui.  "A
    simple approach to measure computed tomography (CT) modulation transfer
    function (MTF) and noise-power spectrum (NPS) using the American College
    of Radiology (ACR) accreditation phantom," Med. Phys. 40, 051907-1 -
    051907-9 (2013). http://dx.doi.org/10.1118/1.4800795

    Parameters
    ----------
    phantom : UnitCircle
        The unit circle phantom.
    A : ndarray
        The reconstruction of the above phantom.
    B : ndarray
        The reconstruction of the above phantom with different noise. This
        second reconstruction enables allows use of trend subtraction instead
        of zero mean normalization.
    plot_type : string
        'histogram' returns a plot binned by radial coordinate wavenumber
        'frequency' returns a wavenumber vs wavenumber plot

    returns
    -------
    bins :
        Bins for the radially binned NPS
    counts :
        NPS values for the radially binned NPS
    X, Y :
        Frequencies for the 2D frequency plot NPS
    NPS : 2Darray
        the NPS for the 2D frequency plot
    '''
    if not isinstance(phantom, UnitCircle):
        raise TypeError('NPS requires unit circle phantom.')
    if not isinstance(A, np.ndarray):
        raise TypeError('A must be numpy.ndarray.')
    if not isinstance(B, np.ndarray):
        raise TypeError('B must be numpy.ndarray.')
    if A.shape != B.shape:
        raise ValueError('A and B must be the same size!')
    if not (plot_type == 'frequency' or plot_type == 'histogram'):
        raise ValueError("plot type must be 'frequency' or 'histogram'.")

    image = A
    if B is not None:
        image = image - B

    # plt.figure()
    # plt.imshow(image, cmap='inferno',interpolation="none")
    # plt.colorbar()
    # plt.show(block=True)

    resolution = image.shape[0]  # [pixels/length]
    # cut out uniform region (square circumscribed by unit circle)
    i_half = int(image.shape[0] / 2)  # half image
    # half of the square inside the circle
    s_half = int(image.shape[0] * phantom.feature[0].radius / np.sqrt(2))
    unif_region = image[i_half - s_half:i_half +
                        s_half, i_half - s_half:i_half + s_half]

    # zero-mean normalization
    unif_region = unif_region - np.mean(unif_region)

    # 2D fourier-transform
    unif_region = np.fft.fftshift(np.fft.fft2(unif_region))
    # squared modulus / squared complex norm
    NPS = np.abs((unif_region))**2  # [attenuation^2]

    # Calculate axis labels
    # TODO@dgursoy is this frequency scaling correct?
    x = y = (np.arange(0, unif_region.shape[0]) /
             unif_region.shape[0] - 0.5) * image.shape[0]
    X, Y = np.meshgrid(x, y)
    # print(x)

    if plot_type == 'histogram':
        # calculate polar coordinates for each position
        R = np.sqrt(X**2 + Y**2)
        # Theta = nothing; we are averaging radial contours

        bin_width = 1  # [length] (R is already converted to length)
        bins = np.arange(0, np.max(R), bin_width)
        # print(bins)
        counts = np.zeros(bins.shape)
        for i in range(0, bins.size):
            if i < bins.size - 1:
                mask = np.bitwise_and(bins[i] <= R, R < bins[i + 1])
            else:
                mask = R >= bins[i]
            # average all the counts for equal radii
            if 0 < np.sum(mask):  # some bins may be empty
                counts[i] = np.mean(NPS[mask])

        plt.figure()
        plt.bar(bins, counts, width=bin_width)
        plt.xlabel('spatial frequency [cycles/length]')
        plt.ylabel('value^2')
        plt.title('Noise Power Spectrum')
        # plt.show(block=False)
        return bins, counts

    elif plot_type == 'frequency':
        plt.figure()
        plt.contourf(X, Y, NPS, cmap='inferno')
        plt.xlabel('spatial frequency [cycles/length]')
        plt.ylabel('spatial frequency [cycles/length]')
        plt.axis('equal')
        plt.colorbar()
        plt.title('Noise Power Spectrum')
        # plt.show(block=False)
        return X, Y, NPS


def compute_neq(phantom, A, B):
    '''Calculates the NEQ according to recommendations by JT Dobbins.

    Parameters
    ----------
    phantom : UnitCircle
        The unit circle class with radius less than 0.5
    A : ndarray
        The reconstruction of the above phantom.
    B : ndarray
        The reconstruction of the above phantom with different noise. This
        second reconstruction enables allows use of trend subtraction instead
        of zero mean normalization.

    Returns
    -------
    mu_b :
        The spatial frequencies
    NEQ :
        the Noise Equivalent Quanta
    '''
    mu_a, NPS = compute_nps(phantom, A, B, plot_type='histogram')
    mu_b, MTF = compute_mtf(phantom, A, Ntheta=1)

    # remove negative MT
    MTF = MTF[:, mu_b > 0]
    mu_b = mu_b[mu_b > 0]

    # bin the NPS data to match the MTF data
    NPS_binned = np.zeros(MTF.shape)
    for i in range(0, mu_b.size):
        bucket = mu_b[i] < mu_a
        if i + 1 < mu_b.size:
            bucket = np.logical_and(bucket, mu_a < mu_b[i+1])

        if NPS[bucket].size > 0:
            NPS_binned[0, i] = np.sum(NPS[bucket])

    NEQ = MTF/np.sqrt(NPS_binned)  # or something similiar

    plt.figure()
    plt.plot(mu_b.flatten(), NEQ.flatten())
    plt.xlabel('spatial frequency [cycles/length]')
    plt.ylabel('value')
    plt.xlim([0, A.shape[0]/2])
    plt.title('Noise Equivalent Quanta')

    return mu_b, NEQ


def probability_mask(phantom, size, ratio=8, uniform=True):
    """Returns the probability mask for each phase in the phantom.

    Parameters
    ------------
    size : scalar
        The side length in pixels of the resulting square image.
    ratio : scalar, optional
        The discretization works by drawing the shapes in a larger space
        then averaging and downsampling. This parameter controls how many
        pixels in the larger representation are averaged for the final
        representation. e.g. if ratio = 8, then the final pixel values
        are the average of 64 pixels.
    uniform : boolean, optional
        When set to False, changes the way pixels are averaged from a
        uniform weights to gaussian weights.

    Returns
    ------------
    image : list of numpy.ndarray
        A list of float masks for each phase in the phantom.
    """

    # Make a higher resolution grid to sample the continuous space
    _x = np.arange(0, 1, 1 / size / ratio)
    _y = np.arange(0, 1, 1 / size / ratio)
    px, py = np.meshgrid(_x, _y)

    phases = {0}  # tracks what values exist in this phantom

    # Draw the shapes to the higher resolution grid
    image = np.zeros((size * ratio, size * ratio), dtype=np.float)
    for m in range(phantom.population):
        x = phantom.feature[m].center.x
        y = phantom.feature[m].center.y
        rad = phantom.feature[m].radius
        val = phantom.feature[m].mass_atten
        # image *= ((px - x)**2 + (py - y)**2 >= rad**2) # partial overlap
        # support
        image += ((px - x)**2 + (py - y)**2 < rad**2) * val

        # collect a list of the unique values in the phantom
        phases = phases | {val}

    # generate a separate mask for each phase
    masks = []
    phases = list(phases)
    phases.sort()
    for m in range(0, len(phases)):
        masks.append(0)

        # First make a boolean array for each value,
        val = phases[m]
        masks[m] = (image == val).astype(float)

        # then use a uniform filter to calculate the local percentage for each
        # phase.
        if uniform:
            masks[m] = scipy.ndimage.uniform_filter(masks[m], ratio)
        else:
            masks[m] = scipy.ndimage.gaussian_filter(masks[m], ratio / 4.)
        # Resample
        masks[m] = masks[m][::ratio, ::ratio]

    return masks


def compute_PCC(A, B, masks=None):
    """ Computes the Pearson product-moment correlation coefficients (PCC) for
    the two images.

    Parameters
    -------------
    A,B : ndarray
        The two images to be compared
    masks : list of ndarrays, optional
        If supplied, the data under each mask is computed separately.

    Returns
    ----------------
    covariances : array, list of arrays
    """
    covariances = []
    if masks is None:
        data = np.vstack((np.ravel(A), np.ravel(B)))
        return np.corrcoef(data)

    for m in masks:
        weights = m[m > 0]
        masked_B = B[m > 0]
        masked_A = A[m > 0]
        data = np.vstack((masked_A, masked_B))
        # covariances.append(np.cov(data,aweights=weights))
        covariances.append(np.corrcoef(data))

    return covariances


def compute_likeness(A, B, masks):
    """ Predicts the likelihood that each pixel in B belongs to a phase based
    on the histogram of A.

    Parameters
    ------------
    A : ndarray
    B : ndarray
    masks : list of ndarrays

    Returns
    --------------
    likelihoods : list of ndarrays
    """
    # generate the pdf or pmf for each of the phases
    pdfs = []
    for m in masks:
        K, mu, std = exponnorm.fit(np.ravel(A[m > 0]))
        print((K, mu, std))
        # for each reconstruciton, plot the likelihood that this phase
        # generates that pixel
        pdfs.append(exponnorm.pdf(B, K, mu, std))

    # determine the probability that it belongs to its correct phase
    pdfs_total = sum(pdfs)
    return pdfs / pdfs_total


def compute_background_ttest(image, masks):
    """Determines whether the background has significantly different luminance
    than the other phases.

    Parameters
    -------------
    image : ndarray

    masks : list of ndarrays
        Masks for the background and any other phases. Does not autogenerate
        the non-background mask because maybe you want to compare only two
        phases.

    Returns
    ----------
    tstat : scalar
    pvalue : scalar
    """

    # separate the background
    background = image[masks[0] > 0]
    # combine non-background masks
    other = False
    for i in range(1, len(masks)):
        other = np.logical_or(other, masks[i] > 0)
    other = image[other]

    tstat, pvalue = ttest_ind(background, other, axis=None, equal_var=False)
    # print([tstat,pvalue])

    return tstat, pvalue


class ImageQuality(object):
    """Stores information about image quality.

    Attributes
    ----------------
    orig : numpy.ndarray
    recon : numpy.ndarray
    qualities : list of scalars
    maps : list of numpy.ndarray
    scales : list of scalars
    """

    def __init__(self, original, reconstruction, method=''):
        self.orig = original.astype(np.float)
        self.recon = reconstruction.astype(np.float)

        if self.orig.shape != self.recon.shape:
            raise ValueError("original and reconstruction should be the " +
                             "same shape")
        if self.orig.ndim != 2:
            raise ValueError("This function only support 2D images.")

        self.qualities = []
        self.maps = []
        self.scales = []
        self.method = method

    def __str__(self):
        return ("QUALITY: " + str(self.qualities) +
                "\nSCALES: " + str(self.scales))

    def __add__(self, other):
        if not isinstance(other, ImageQuality):
            raise TypeError("Can only add ImageQuality to ImageQuality")

        self.qualities += other.qualities
        self.maps += other.maps
        self.scales += other.scales
        return self

    def add_quality(self, quality, scale, maps=None):
        '''
        Parameters
        -----------
        quality : scalar, list
            The average quality for the image
        map : array, list of arrays, optional
            the local quality rating across the image
        scale : scalar, list
            the size scale at which the quality was calculated
        '''
        if (isinstance(quality, list) and isinstance(scale, list) and
           (maps is None or isinstance(maps, list))):
            self.qualities += quality
            self.scales += scale
            if maps is None:
                maps = [None] * len(quality)
            self.maps += maps
        elif (isinstance(quality, float) and isinstance(scale, float) and
              (maps is None or isinstance(maps, np.ndarray))):
            self.qualities.append(quality)
            self.scales.append(scale)
            self.maps.append(maps)
        else:
            raise TypeError

    def sort(self):
        """Sorts the qualities by scale"""
        raise NotImplementedError


def compute_quality(reference, reconstructions, method="MSSSIM", L=1):
    """
    Computes image quality metrics for each of the reconstructions.

    Parameters
    ---------
    reference : array
        the discrete reference image. In a future release, we will
        determine the best way to compare a continuous domain to a discrete
        reconstruction.
    reconstructions : list of arrays
        A list of discrete reconstructions
    method : string, optional
        The quality metric desired for this comparison.
        Options include: SSIM, MSSSIM
    L : scalar
        The dynamic range of the data. This value is 1 for float
        representations and 2^bitdepth for integer representations.

    Returns
    ---------
    metrics : list of ImageQuality
    """
    if L < 1:
        raise ValueError("Dynamic range must be >= 1.")
    if not isinstance(reconstructions, list):
        reconstructions = [reconstructions]

    dictionary = {"SSIM": _compute_ssim, "MSSSIM": _compute_msssim,
                  "VIFp": _compute_vifp, "FSIM": _compute_fsim}
    try:
        method_func = dictionary[method]
    except KeyError:
        ValueError("That method is not implemented.")

    metrics = []
    for image in reconstructions:
        IQ = ImageQuality(reference, image, method)
        IQ = method_func(IQ, L=L)
        metrics.append(IQ)

    return metrics


def _compute_vifp(imQual, nlevels=5, sigma=1.2, L=None):
    """Calculates the Visual Information Fidelity (VIFp) between two images in
    in a multiscale pixel domain with scalar.

-----------COPYRIGHT NOTICE STARTS WITH THIS LINE------------
Copyright (c) 2005 The University of Texas at Austin
All rights reserved.

Permission is hereby granted, without written agreement and without license or
royalty fees, to use, copy, modify, and distribute this code (the source files)
and its documentation for any purpose, provided that the copyright notice in
its entirety appear in all copies of this code, and the original source of this
code, Laboratory for Image and Video Engineering
(LIVE, http://live.ece.utexas.edu) at the University of Texas at Austin
(UT Austin, http://www.utexas.edu), is acknowledged in any publication that
reports research using this code. The research is to be cited in the
bibliography as:

H. R. Sheikh and A. C. Bovik, "Image Information and Visual Quality", IEEE
Transactions on Image Processing, (to appear).

IN NO EVENT SHALL THE UNIVERSITY OF TEXAS AT AUSTIN BE LIABLE TO ANY PARTY FOR
DIRECT, INDIRECT, SPECIAL, INCIDENTAL, OR CONSEQUENTIAL DAMAGES ARISING OUT OF
THE USE OF THIS DATABASE AND ITS DOCUMENTATION, EVEN IF THE UNIVERSITY OF TEXAS
AT AUSTIN HAS BEEN ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

THE UNIVERSITY OF TEXAS AT AUSTIN SPECIFICALLY DISCLAIMS ANY WARRANTIES,
INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND
FITNESS FOR A PARTICULAR PURPOSE. THE DATABASE PROVIDED HEREUNDER IS ON AN "AS
IS" BASIS, AND THE UNIVERSITY OF TEXAS AT AUSTIN HAS NO OBLIGATION TO PROVIDE
MAINTENANCE, SUPPORT, UPDATES, ENHANCEMENTS, OR MODIFICATIONS.
-----------COPYRIGHT NOTICE ENDS WITH THIS LINE------------

    Parameters
    -----------
    imQual : ImageQuality
        A struct used to organize image quality information.
    nlevels : scalar
        The number of levels to measure quality.
    sigma : scalar
        The size of the quality filter at the smallest scale.

    Returns
    -----------
    imQual : ImageQuality
        A struct used to organize image quality information. NOTE: the valid
        range for VIFp is (0, 1].
    """
    _full_reference_input_check(imQual, sigma, nlevels, L)

    ref = imQual.orig
    dist = imQual.recon

    sigmaN_sq = 2  # used to tune response
    eps = 1e-10

    for level in range(0, nlevels):
        # Downsample (using ndimage.zoom to prevent sampling bias)
        if (level > 0):
            ref = scipy.ndimage.zoom(ref, 1/2)
            dist = scipy.ndimage.zoom(dist, 1/2)

        mu1 = scipy.ndimage.gaussian_filter(ref, sigma)
        mu2 = scipy.ndimage.gaussian_filter(dist, sigma)

        sigma1_sq = scipy.ndimage.gaussian_filter((ref - mu1)**2, sigma)
        sigma2_sq = scipy.ndimage.gaussian_filter((dist - mu2)**2, sigma)
        sigma12 = scipy.ndimage.gaussian_filter((ref - mu1) * (dist - mu2),
                                                sigma)

        g = sigma12 / (sigma1_sq + eps)
        sigmav_sq = sigma2_sq - g * sigma12

        # Calculate VIF
        numator = np.log2(1 + g**2 * sigma1_sq / (sigmav_sq + sigmaN_sq))
        denator = np.sum(np.log2(1 + sigma1_sq / sigmaN_sq))

        vifmap = numator / denator
        vifp = np.sum(vifmap)
        # Normalize the map because we want values between 1 and 0
        vifmap *= vifmap.size

        scale = sigma * 2**level
        imQual.add_quality(vifp, scale, maps=vifmap)

    return imQual


def _compute_fsim(imQual, nlevels=5, nwavelets=16, L=None):
    """
    FSIM Index with automatic downsampling, Version 1.0
    Copyright(c) 2010 Lin ZHANG, Lei Zhang, Xuanqin Mou and David Zhang
    All Rights Reserved.
    ----------------------------------------------------------------------
    Permission to use, copy, or modify this software and its documentation
    for educational and research purposes only and without fee is here
    granted, provided that this copyright notice and the original authors'
    names appear on all copies and supporting documentation. This program
    shall not be used, rewritten, or adapted as the basis of a commercial
    software or hardware product without first obtaining permission of the
    authors. The authors make no representations about the suitability of
    this software for any purpose. It is provided "as is" without express
    or implied warranty.
    ----------------------------------------------------------------------
    Lin Zhang, Lei Zhang, Xuanqin Mou, and David Zhang,"FSIM: a feature
    similarity index for image qualtiy assessment", IEEE Transactions on Image
    Processing, vol. 20, no. 8, pp. 2378-2386, 2011.

    ----------------------------------------------------------------------
    An implementation of the algorithm for calculating the Feature SIMilarity
    (FSIM) index was ported to Python. This implementation only considers the
    luminance component of images. For multichannel images, convert to
    grayscale first. Dynamic range should be 0-255.

    Parameters
    --------------------------
    imQual : ImageQuality
        A struct used to organize image quality information.
    nlevels : scalar
        The number of levels to measure quality.
    nwavelets : scalar
        The number of wavelets to use in the phase congruency calculation.

    Returns
    ------------------
    imQual : ImageQuality
        A struct used to organize image quality information. NOTE: the valid
        range for FSIM is (0, 1].
    """
    _full_reference_input_check(imQual, 1.2, nlevels, L)
    if nwavelets < 1:
        raise ValueError('There must be at least one wavelet level.')

    Y1 = imQual.orig
    Y2 = imQual.recon

    for scale in range(0, nlevels):
        # sigma = 1.2 is approximately correct because the width of the scharr
        # and min wavelet filter (phase congruency filter) is 3.
        sigma = 1.2 * 2**scale

        F = 2  # Downsample (using ndimage.zoom to prevent sampling bias)
        Y1 = scipy.ndimage.zoom(Y1, 1/F)
        Y2 = scipy.ndimage.zoom(Y2, 1/F)

        # Calculate the phase congruency maps
        [PC1, Orient1, ft1, T1] = _phasecongmono(Y1, nscale=nwavelets)
        [PC2, Orient2, ft2, T2] = _phasecongmono(Y2, nscale=nwavelets)

        # Calculate the gradient magnitude map using Scharr filters
        dx = np.array([[3., 0., -3.],
                       [10., 0., -10.],
                       [3., 0., -3.]]) / 16
        dy = np.array([[3., 10., 3.],
                       [0., 0., 0.],
                       [-3., -10., -3.]]) / 16

        IxY1 = scipy.ndimage.filters.convolve(Y1, dx)
        IyY1 = scipy.ndimage.filters.convolve(Y1, dy)
        gradientMap1 = np.sqrt(IxY1**2 + IyY1**2)

        IxY2 = scipy.ndimage.filters.convolve(Y2, dx)
        IyY2 = scipy.ndimage.filters.convolve(Y2, dy)
        gradientMap2 = np.sqrt(IxY2**2 + IyY2**2)

        # Calculate the FSIM
        T1 = 0.85   # fixed and depends on dynamic range of PC values
        T2 = 160    # fixed and depends on dynamic range of GM values
        PCSimMatrix = (2 * PC1 * PC2 + T1) / (PC1**2 + PC2**2 + T1)
        gradientSimMatrix = ((2 * gradientMap1 * gradientMap2 + T2) /
                             (gradientMap1**2 + gradientMap2**2 + T2))
        PCm = np.maximum(PC1, PC2)
        FSIMmap = gradientSimMatrix * PCSimMatrix
        FSIM = np.sum(FSIMmap * PCm) / np.sum(PCm)
        imQual.add_quality(FSIM, sigma, maps=FSIMmap)

    return imQual


def _compute_msssim(imQual, nlevels=5, sigma=1.2, L=1, K=(0.01, 0.03)):
    '''
    An implementation of the Multi-Scale Structural SIMilarity index (MS-SSIM).

    References
    -------------
    Multi-scale Structural Similarity Index (MS-SSIM)
    Z. Wang, E. P. Simoncelli and A. C. Bovik, "Multi-scale structural
    similarity for image quality assessment," Invited Paper, IEEE Asilomar
    Conference on Signals, Systems and Computers, Nov. 2003

    Parameters
    -------------
    imQual : ImageQuality
    nlevels : int
        The max number of levels to analyze
    sigma : float
        Sets the standard deviation of the gaussian filter. This setting
        determines the minimum scale at which quality is assessed.
    L : scalar
        The dynamic range of the data. This value is 1 for float
        representations and 2^bitdepth for integer representations.
    K : 2-tuple
        A list of two constants which help prevent division by zero.

    Returns
    -------
    imQual : ImageQuality
        A struct used to organize image quality information. NOTE: the valid
        range for SSIM is [-1, 1].
    '''
    _full_reference_input_check(imQual, sigma, nlevels, L)

    img1 = imQual.orig
    img2 = imQual.recon

    # The relative imporance of each level as determined by human experiment
    # weight = [0.0448, 0.2856, 0.3001, 0.2363, 0.1333]

    for l in range(0, nlevels):
        imQual += _compute_ssim(ImageQuality(img1, img2), sigma=sigma, L=L,
                                K=K, scale=sigma * 2**l)
        if l == nlevels - 1:
            break

        # Downsample (using ndimage.zoom to prevent sampling bias)
        img1 = scipy.ndimage.zoom(img1, 1/2)
        img2 = scipy.ndimage.zoom(img2, 1/2)

    return imQual


def _compute_ssim(imQual, sigma=1.2, L=1, K=(0.01, 0.03), scale=None):
    """
    A modified version of the Structural SIMilarity index (SSIM) based on an
    implementation by Helder C. R. de Oliveira, based on the implementation by
    Antoine Vacavant, ISIT lab, antoine.vacavant@iut.u-clermont1.fr
    http://isit.u-clermont1.fr/~anvacava

    References
    ----------
    Z. Wang, A. C. Bovik, H. R. Sheikh and E. P. Simoncelli. Image quality
    assessment: From error visibility to structural similarity. IEEE
    Transactions on Image Processing, 13(4):600--612, 2004.

    Z. Wang and A. C. Bovik. Mean squared error: Love it or leave it? - A new
    look at signal fidelity measures. IEEE Signal Processing Magazine,
    26(1):98--117, 2009.

    Attributes
    ----------
    imQual : ImageQuality
    L : scalar
        The dynamic range of the data. This value is 1 for float
        representations and 2^bitdepth for integer representations.
    sigma : list, optional
        The standard deviation of the gaussian filter.

    Returns
    -------
    imQual : ImageQuality
        A struct used to organize image quality information. NOTE: the valid
        range for SSIM is [-1, 1].
    """
    _full_reference_input_check(imQual, sigma, 1, L)
    if scale is not None and scale <= 0:
        raise ValueError("Scale cannot be negative or zero.")

    if scale is None:
        scale = sigma

    c_1 = (K[0] * L)**2
    c_2 = (K[1] * L)**2

    # Convert image matrices to double precision (like in the Matlab version)
    img1 = imQual.orig
    img2 = imQual.recon

    # Means obtained by Gaussian filtering of inputs
    mu_1 = scipy.ndimage.filters.gaussian_filter(img1, sigma)
    mu_2 = scipy.ndimage.filters.gaussian_filter(img2, sigma)

    # Squares of means
    mu_1_sq = mu_1**2
    mu_2_sq = mu_2**2
    mu_1_mu_2 = mu_1 * mu_2

    # Squares of input matrices
    im1_sq = img1**2
    im2_sq = img2**2
    im12 = img1 * img2

    # Variances obtained by Gaussian filtering of inputs' squares
    sigma_1_sq = scipy.ndimage.filters.gaussian_filter(im1_sq, sigma)
    sigma_2_sq = scipy.ndimage.filters.gaussian_filter(im2_sq, sigma)

    # Covariance
    sigma_12 = scipy.ndimage.filters.gaussian_filter(im12, sigma)

    # Centered squares of variances
    sigma_1_sq -= mu_1_sq
    sigma_2_sq -= mu_2_sq
    sigma_12 -= mu_1_mu_2

    if (c_1 > 0) & (c_2 > 0):
        ssim_map = (((2 * mu_1_mu_2 + c_1) * (2 * sigma_12 + c_2)) /
                    ((mu_1_sq + mu_2_sq + c_1) *
                     (sigma_1_sq + sigma_2_sq + c_2)))
    else:
        numerator1 = 2 * mu_1_mu_2 + c_1
        numerator2 = 2 * sigma_12 + c_2

        denominator1 = mu_1_sq + mu_2_sq + c_1
        denominator2 = sigma_1_sq + sigma_2_sq + c_2

        ssim_map = np.ones(mu_1.size)

        index = (denominator1 * denominator2 > 0)

        ssim_map[index] = ((numerator1[index] * numerator2[index]) /
                           (denominator1[index] * denominator2[index]))
        index = (denominator1 != 0) & (denominator2 == 0)
        ssim_map[index] = (numerator1[index] / denominator1[index])**4

    # return SSIM
    index = np.mean(ssim_map)
    imQual.add_quality(index, scale, maps=ssim_map)
    return imQual


def _full_reference_input_check(imQual, sigma, nlevels, L):
    """Checks full reference quality measures for valid inputs."""
    if not isinstance(imQual, ImageQuality):
        raise TypeError
    if nlevels <= 0:
        raise ValueError('nlevels must be >= 1.')
    if sigma < 1.2:
        raise ValueError('sigma < 1.2 is effective meaningless.')
    if np.min(imQual.orig.shape) / (2**(nlevels - 1)) < sigma * 2:
        raise ValueError("The image becomes smaller than the filter size! " +
                         "Decrease the number of levels.")
    if L is not None and L < 1:
        raise ValueError("Dynamic range must be >= 1.")
