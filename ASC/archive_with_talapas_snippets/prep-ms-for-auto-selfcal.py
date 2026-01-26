import numpy as np
import os
import pandas as pd
import shutil
import sys
import time

from datetime import datetime

# read params from config.yaml
measurement_set = "24A-322.ASASSN-14ae.2024-08-08.ms"
source_name = "ASASSN-14ae"

# Function to scrape a listfile for information needed for tclean ================================================================
# Inputs:
#     listfile (str): path/to/listfile.txt, which was automatically created in location of measurement set in main
#     source_name (str): user-specified name of source, like "ASASSN-14ae"
#     band (str): user-specified VLA band to image, like "C"
#     use_manual_spws (boolean): trigger in main to use own spectral windows and overwrite those in the band
#     manual_spws (str): manual spectral windows, either in a range using ~ or all comma separated: combinations not yet supported
# Returns:
#     field (str): index of source in listfile
#     cell_size (float): resolution [arcsec/pixel] of image, calculated by dividing the synthesized beamwidth by a factor of 4, as is recommended by NRAO
#     spw_range (str): spectral window range to image, given in format 'start_spw~stop_spw'
#     central_freq (float): central frequency of VLA band given
#     ra (str) and dec (str): coordinates of source
def scrape_listfile(listfile, source_name):

    # open listfile
    with open(listfile) as f:
        lines = f.read().splitlines()
    
    # open VLA configuration schedule and resolution tables
    df_resolution = pd.read_csv("vla-resolution.csv")
    df_resolution = df_resolution.loc[:, ~df_resolution.columns.str.contains('^Unnamed')]
    df_schedule = pd.read_csv("vla-configuration-schedule.csv")
    
    # loop through lines to find important lines
    for i, line in enumerate(lines):
        if "Fields" in line:
            field_line = line
            field_indx = i
    
        if "Spectral Windows" in line:
            spw_line = line
            spw_indx = i
    
        # determine on which line the observation datetimes are listed
        if "Observed from" in line:
            time_line = line
            time_indx = i
    
    # FIELD ===============================================
    nfields = int(field_line.split(" ")[-1][0])
    ls = [lines[field_indx+1+i] for i in range(nfields+1)]
    for l in ls:
        if source_name in l:
            field = l.split()[0]
            ra = l.split()[3]
            dec = l.split()[4]
    
    # CONFIGURATION =======================================
    # find start and finish time for observations
    t0 = time_line.split()[2]
    t1 = time_line.split()[4]
    
    # convert to datetime objects
    lf_date_format = "%d-%b-%Y/%H:%M:%S.%f"
    date0 = datetime.strptime(t0, lf_date_format)
    date1 = datetime.strptime(t1, lf_date_format)
    
    df_date_format = "%Y %b %d"
    # find the row in the schedule dataframe that encapsulates the observation
    for i, row in df_schedule.iterrows():
        start_epoch = datetime.strptime(row["observing_start"], df_date_format)
        end_epoch = datetime.strptime(row["observing_end"], df_date_format)
    
        if (start_epoch <= date0) and (date0 < end_epoch):
            configuration = row["configuration"]
    
    # CELL SIZE ==============================================
    #central_freq = (df_resolution[df_resolution["band"] == band]["central_freq"].values[0]).item()
    #synthesized_beamwidth = df_resolution[df_resolution["band"] == band][configuration].values[0].item()
    #cell_size = synthesized_beamwidth/4
    
    # SPECTRAL WINDOWS =================================================
    # determine how many spectral windows there are
    nspws = int(spw_line.split(' ')[3].split('(')[-1])
    ls = [lines[spw_indx+1+i] for i in range(nspws+1)]
    
    # get formatting right
    result = []
    for line in ls:
        row = list(filter(None, line.split(' ')))
        result.append(row)
    
    # save as dataframe
    cols = result[0]
    cols = cols[0:8]+["BBC-Num", "Corr1", "Corr2", "Corr3", "Corr4"]
    data = result[1:]
    df = pd.DataFrame(data, columns=cols)

    # get list of bands in listfile
    bands = list(set([df["Name"].iloc[i].split("#")[0] for i in range(df.shape[0])]))
    
    rows_list = []
    for i, band in enumerate(bands):
    
        # cell size
        #central_freq = (df_resolution[df_resolution["band"] == band]["central_freq"].values[0]).item()
        central_freq = (df_resolution[df_resolution["band"] == band]["central_freq"]).item()
        synthesized_beamwidth = (df_resolution[df_resolution["band"] == band][configuration]).item()
        cell_size = synthesized_beamwidth/4
    
        # get section of df for the band
        in_band = [band+"#" in b for b in list(df["Name"].values)]
        indxs = np.where(in_band)[0]
        df_band = df.iloc[indxs]
    
        # remove two cal spws from X-band
        #if band == "EVLA_X":
        #    df_band = df_band.iloc[2:]
    
        # split into frequency bands
        nspws = df_band.shape[0]
        df_lower = df_band.iloc[0:int(nspws/2)]
        df_upper = df_band.iloc[int(nspws/2):df_band.shape[0]]
        df_all = df_band
    
        # lower
        freq_ghz = round(df_lower["CtrFreq(MHz)"].values.astype(float).mean()/1000, 2)
        spws = df_lower["SpwID"].values.astype(int)
        spw_range = f"{min(spws)}~{max(spws)}"
        rows_list.append({"band":band, "split":"lower", "freq [GHz]":freq_ghz, "spws":spw_range, "cell size [arcsec/pixel]":cell_size})
    
        # upper
        freq_ghz = round(df_upper["CtrFreq(MHz)"].values.astype(float).mean()/1000, 2)
        spws = df_upper["SpwID"].values.astype(int)
        spw_range = f"{min(spws)}~{max(spws)}"
        rows_list.append({"band":band, "split":"upper", "freq [GHz]":freq_ghz, "spws":spw_range, "cell size [arcsec/pixel]":cell_size})

        # all
        freq_ghz = round(df_all["CtrFreq(MHz)"].values.astype(float).mean()/1000, 2)
        spws = df_all["SpwID"].values.astype(int)
        spw_range = f"{min(spws)}~{max(spws)}"
        rows_list.append({"band":band, "split":"all", "freq [GHz]":freq_ghz, "spws":spw_range, "cell size [arcsec/pixel]":cell_size})

    df_store = pd.DataFrame(rows_list)#columns=["band", "split", "freq [GHz]", "spws", "cell size [arcsec/pixel]"])
    df_store = df_store.sort_values(by=["freq [GHz]"])
    df_store = df_store.reset_index(drop=True)

    return df_store, field


def split_ms(df_store, measurement_set_target):

    freq_directories = []
    for i, row in df_store.iterrows():
        spws = row["spws"]
        freq = f"{row['freq [GHz]']}GHz"
        band = row["band"]

        freq_directory = f"{ms_directory}/{freq}"
        if not os.path.exists(freq_directory):
            os.makedirs(freq_directory)

        outputvis_name = f"{freq_directory}/{ms_prefix}.{band}.{freq}_target.ms"
        split(vis=measurement_set, spw=spws, outputvis=outputvis_name)
        freq_directories.append(freq_directory)

    return freq_directories

# where things are
ms_directory = os.path.dirname(measurement_set)
auto_sc_files_directory = "/gpfs/projects/nova/auto_selfcal"

# create listfile and scrape for tclean parameters
listfile = ms_directory+"/listfile.txt"
listobs(vis=measurement_set, listfile=listfile, overwrite=True)
print(f"Created listfile {listfile} \n")
df_store, field = scrape_listfile(listfile, source_name)

# split original measurement set into _target measurement set
ms_prefix = os.path.splitext(measurement_set)[0]
measurement_set_target = f"{ms_prefix}_target.ms"
print(f"Splitting into _target.ms")
split(vis=measurement_set, field=field, outputvis=measurement_set_target)

print(f"Splitting into {df_store.shape[0]} measurement sets")
split_ms_directories = split_ms(df_store, measurement_set_target)

batch_files = []
for split_ms_directory in split_ms_directories:

    split_ms_name = os.path.splitext(split_ms_directory.split("/")[-1])[0]

    # move all the files from the auto_sc directory into directory
    shutil.copytree(auto_sc_files_directory, split_ms_directory)

    # write batch file
    job_base = f"auto_selfcal_{split_ms_name}"
    chdir_path = f"{split_ms_directory}"
    
    # Define the job script filename
    job_script = f"{job_base}.sh"
    
    # Create the SLURM job script content
    job_script_content = f"""#!/bin/bash
    
    #SBATCH --account=nova
    #SBATCH --partition=preempt
    #SBATCH --job-name={job_base}
    #SBATCH --output={job_base}.out
    #SBATCH --error={job_base}.err
    #SBATCH --time=7-00:00:00
    #SBATCH --mem=64GB
    #SBATCH --nodes=1
    #SBATCH --ntasks-per-node=1
    #SBATCH --cpus-per-task=1
    #SBATCH --chdir={chdir_path}
    
    echo "loading casa"
    module load casa/6.7.0
    echo "loaded casa"
    
    echo "about to run auto_selfcal.py"
    casa -c auto_selfcal.py
    """
    
    # Write the job script to a file
    with open(job_script, "w") as f:
        f.write(job_script_content)
    
    print(f"Job script {job_script} created.")