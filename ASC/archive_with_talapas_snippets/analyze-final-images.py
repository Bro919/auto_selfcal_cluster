from astropy.io import fits
from casatools import image
import glob
import numpy as np
import os
import pandas as pd
import re
import shutil
import sys
import time
import yaml
from datetime import datetime

# image name is {measurement_set_name}.{freq}GHz.{image_size}px.image.tt0
# for self-cal, {measurement_set_name}.{freq}GHz.auto_selfcal.image.tt0

# define measurement set name
#measurement_set_name = "24A-322.ASASSN-14ae.2024-08-08"
source_name = "ASASSN-14ae"
obs_date = "2024-08-08"
ra, dec = "11:08:40.11","34.05.52.2"
#band = "EVLA_C"
#freq = 6

# get list of images
image_directory = f"/Users/jimmylynch/Desktop/radio/observations/24A-322/ASASSN-14ae/24A-322.ASASSN-14ae.2024-08-08/final_images"
pattern = os.path.join(image_directory, "*.image.tt0")
image_paths = glob.glob(pattern)
#image_paths = [f"{image_directory}/25A-060.AT2018bsi.2025-05-24.6.0GHz.auto_selfcal.image.tt0"]

# set up log information
freqs = []
fluxes, flux_errs, rmses, strengths, detections, results, dynamic_ranges = [], [], [], [], [], [], []
logfile_path = f"{image_directory}/auto_selfcal.flux_measurements.csv"

def get_cell_size(obs_date, band):

    # open VLA configuration schedule and resolution tables
    df_resolution = pd.read_csv("vla-resolution.csv")
    df_resolution = df_resolution.loc[:, ~df_resolution.columns.str.contains('^Unnamed')]
    df_schedule = pd.read_csv("vla-configuration-schedule.csv")
    
    # convert to datetime objects
    lf_date_format = "%Y-%m-%d"
    date0 = datetime.strptime(obs_date, lf_date_format)
    
    df_date_format = "%Y %b %d"
    # find the row in the schedule dataframe that encapsulates the observation
    for i, row in df_schedule.iterrows():
        start_epoch = datetime.strptime(row["observing_start"], df_date_format)
        end_epoch = datetime.strptime(row["observing_end"], df_date_format)
    
        if (start_epoch <= date0) and (date0 < end_epoch):
            configuration = row["configuration"]

    # get cell_size
    central_freq = (df_resolution[df_resolution["band"] == band]["central_freq"].values[0]).item()
    synthesized_beamwidth = df_resolution[df_resolution["band"] == band][configuration].values[0].item()
    cell_size = synthesized_beamwidth/4

    return cell_size

def convert_to_fits(image_path, image_prefix, ra, dec, crop_size=128):

    output_image_name = f"{image_prefix}.{crop_size}px.fits"

    # open image
    ia = image()
    ia.open(image_path)
    
    # get image coordinate system
    cs = ia.coordsys()
    pix_center = cs.topixel({'type': 'direction', 'ra': ra, 'dec': dec})['numeric']
    pix_x, pix_y = int(round(pix_center[0])), int(round(pix_center[1]))
    
    # define pixel range for cropping
    half = crop_size // 2
    x1 = f"{pix_x - half}pix"
    y1 = f"{pix_y - half}pix"
    x2 = f"{pix_x + half - 1}pix"
    y2 = f"{pix_y + half - 1}pix"
    crop_region = f"box[[{x1}, {y1}], [{x2}, {y2}]]"
    
    # extract subimage
    subimage_name = 'cropped.image'
    if os.path.exists(subimage_name):
        os.system(f"rm -rf {subimage_name}")
    ia.subimage(outfile=subimage_name, region=crop_region)
    ia.close()
    
    # scale to be 99.95% 
    ia.open(subimage_name)
    data = ia.getchunk()
    ia.close()
    
    # get min and max for 99.95% clip
    #flat_data = data[0, 0, :, :].flatten()
    #low, high = np.percentile(flat_data, [0.05, 99.95])  # middle 99.9% range
    #scaled_data = np.clip(data[0, 0], low, high)

    # write to fits
    # make sure to flip CASA axes from [chan, stokes, y, x] to [y, x]
    output_image_path = f"{image_directory}/{output_image_name}"
    if not os.path.exists(output_image_path):
        exportfits(subimage_name, fitsimage=output_image_path)
        print(f"Wrote {output_image_name} to fits")
    else:
        print(f"{output_image_name} already exists")

    return output_image_name

def fit_point_source(image_name, region_flux, region_rms, region_non_detection):

    near_source_imstat_results = imstat(imagename=image_name, region=region_rms)
    near_source_rms = near_source_imstat_results["rms"][0]
    
    # if imfit works, it found something to fit to, but not necessarily your source
    # it's good to check manually by opening the image in CARTA
    try:
        rms = near_source_rms
        imfit_results = imfit(imagename=image_name, region=region_flux, rms=rms)
    
        flux = imfit_results["results"]["component0"]["flux"]["value"][0]
        flux_err = imfit_results["results"]["component0"]["flux"]["error"][0]
        strength = flux/rms
    
        # just in case imfit does work but there isn't a 3 sigma detection
        if strength >= 3:
            detection = True
            result = "imfit success"
        else:
            flux = 3*rms
            flux_err = 0
            detection = False
            result = "imfit success, <3 RMS"

    # if there is nothing there, imfit will fail. Reporting flux as 3x the rms from imstat
    except:
        print(f"Imfit failed: check results carefully!")
        imstat_results = imstat(imagename=image_name, region=region_non_detection)
        rms = imstat_results["rms"][0]
        flux = 3*rms
        flux_err = 0
        strength = 0
        detection = False
        result = "imfit fail: flux is 3*RMS"

    # returning values in mJy
    return round(flux*1000, 3), round(flux_err*1000, 3), round(rms*1000, 3), round(strength, 1), detection, result

# loop through images
for image_path in image_paths:
    image_name = image_path.split("/")[-1] # has suffix .image.tt0

    band = image_name.split(".")[3]
    match = re.search(r'(\d+\.\d+)GHz', image_name)
    if match:
        freq = match.group(1)
    image_prefix = image_name[:-len(".image.tt0")]

    # get cell size
    cell_size = get_cell_size(obs_date, band)
    
    imstat_results = imstat(imagename=image_path)
    rms_image = imstat_results["rms"][0]
    max_image = imstat_results["max"][0]
    dynamic_range = round(max_image/rms_image, 1)
    dynamic_ranges.append(dynamic_range)

    # define region for detection fit: using 2.5 times the synthesized beamwidth centered on source
    radius_of_fit = 10*cell_size
    region_flux = f"circle[[{ra}, {dec}], {radius_of_fit}arcsec]"

    # define region for near-source RMS measurement: using annulus with 100 synthesized beams squared area
    inner_rad_annulus = 10*cell_size
    outer_rad_annulus = 22.5*cell_size
    region_rms = f"annulus[[{ra}, {dec}], [{inner_rad_annulus}arcsec, {outer_rad_annulus}arcsec]]"

    # define region for on-source RMS measurement if non-detection: using circle with outer annulus size
    region_non_detection = f"circle[[{ra}, {dec}], {outer_rad_annulus}arcsec]"

    # try the fit and print values
    flux, flux_err, rms, strength, detection, result = fit_point_source(image_path, 
                                                                        region_flux, 
                                                                        region_rms, 
                                                                        region_non_detection)
    
    if detection:
        print(f"Detection at {freq}: {flux} ± {flux_err} mJy.")
        print(f"RMS: {rms} mJy/beam")
    else:
        print(f"Non-detection at {freq}: <{flux} mJy")

    # append values to 
    freqs.append(float(freq))
    fluxes.append(flux)
    flux_errs.append(flux_err)
    rmses.append(rms)
    strengths.append(strength)
    detections.append(detection)
    results.append(result)

    # scale image to be size
    output_fits_image = convert_to_fits(image_path, image_prefix, ra, dec)

# write logfile
df_store = pd.DataFrame()
df_store["Freq [GHz]"] = freqs
df_store["Flux [mJy]"] = fluxes
df_store["Flux_err [mJy]"] = flux_errs
df_store["RMS [mJy]"] = rmses
df_store["Flux/RMS [-]"] = strengths
df_store["Detection"] = detections
df_store["Fit result"] = results
df_store["Dynamic range"] = dynamic_ranges

df_sorted = df_store.sort_values(by="Freq [GHz]").reset_index()

df_sorted.to_csv(logfile_path)