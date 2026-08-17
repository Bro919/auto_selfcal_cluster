# RUNNING INITIAL CALIBRATION OR AUTO SELF-CALIBRATION
Many of the initial Auto-Selfcal scripts are forked from the work done by Jimmy Lynch (https://github.com/jlynch2195/auto_selfcal_cluster), and this repo also uses his auto-image-VLA (https://github.com/jlynch2195/auto-image-VLA) as a submodule. As Jimmy mentions, this also uses the auto_selfcal code developed by Patrick Sheehan (https://github.com/psheehan/auto_selfcal), so full credit goes to them for the basis of this project. Unlike Jimmy's original project, Patrick Sheehan's work is installed here as a submodule, so no extra installation step is needed. This project also makes use of the CASA calibration pipeline script supplied by NRAO.

This repo is set up as an automation wrapper around their code, with the use case of the NRAO cluster and Talapas specifically in mind.

My main use case has been on the NRAO cluster. Read through Jimmy's repo to get an idea of how to request access and make basic use of the cluster. He also comments on best use cases and how his scripts make use of Patrick Sheehan's work. I recommend fully reading Jimmy's README before this one since I skip many of the points he already covers. If this README has drifted from Jimmy's, his original one is still inside the ASC directory.

## Making use of auto-calibration
The main wrapper you should use is auto-calibration.py in the top-level directory. It calls scripts/wrappers in the ASC, CB, and runtime directories. It handles downloading, setting up a working directory, preparing data, and submitting Slurm jobs.

It can handle:
- SDM-BDF datasets for initial calibration (CB) to create a .ms directory
- Auto-SelfCal (ASC) on an existing .ms directory
- Chaining CB directly into ASC
- Standalone auto-image runs

auto-calibration has a lot of flags and parameters for customization. Leave them at defaults unless you know exactly what you want to change.

# Setup
Since I have mostly run this project on the cluster, that is what I default to here.

You need to request account access with NRAO to use the cluster. They will give you an nm member number that you use to log in.
Then open your terminal and use `ssh nm-XXXXX@guest-login.aoc.nrao.edu` to log in with your NRAO account password.

### OS consideration
One important consideration is your OS.
- If you are using macOS, you should be fine since your terminal is already bash-friendly.
- If you are using Linux, you are also fine.
- If you are on Windows, use PuTTY or WSL. I prefer WSL, but either works. If you use WSL, use Ubuntu. Once PuTTY/WSL is set up, you should have a bash terminal.

## Installing the repo
After logging in, use `ssh nmpost-master` to move to the master node, then request an interactive node with `nodescheduler -r 3` (requests 3 days).

You need to do this any time you run auto-calibration or related scripts on the cluster. Try not to request excessive time and hog nodes since only one person can use them interactively at a time.

Run `squeue -l --me` to see which node was assigned, then use `ssh nmpostXXX` to move to it.

Go to your main directory with `cd`, then clone the repo:
```git clone --recurse-submodules https://github.com/Odyia/auto_selfcal_cluster
```

If you already cloned it without submodules, run:
```git submodule update --init --recursive
```

You may need to `cd` into the repo before running that command.

## Contents
As mentioned above, you should mainly use the auto-calibration wrapper. The main wrapper scripts are in runtime, while CB/ASC specific scripts are in their respective directories. The logs directory collects Slurm and metadata outputs to keep the main directory cleaner, and submodules are stored in repo.

## Requesting Data
You can run this using local data (covered below), but most commonly you will run auto-calibration with a URL from the NRAO archive: https://data.nrao.edu/portal/#/

Make sure you are logged in with your NRAO account so you can access your data. Depending on pipeline:
- CB expects SDM-BDF style source data
- ASC expects a calibrated Measurement Set source (.ms)

NRAO will process your request and email you a link to the directory.

# Running auto-calibration
After requesting data and receiving the link, you can run auto-calibration.

IMPORTANT:
ASC can create many Slurm jobs, and A-config runs can take around 7-10 days. With common settings (split=both across multiple bands), you can see around 12 frequency jobs plus one cleanup job. Do not run multiple heavy ASC datasets at once unless you know your resource limits.

CB typically submits two chained jobs (calibration, then auto-image) when auto-image is available, and it is usually done within a day.

To run, enter the directory:
`cd auto_selfcal_cluster/`

### Running CB
For CB:
`python auto-calibration.py --pipeline cb --url 'your-link-goes-here'`

If your SDM-BDF source is local (not a URL), still use --url, but point it to the local path:
`python auto-calibration.py --pipeline cb --url '/path/to/local/SDM-BDF-or-observation-dir'`

Only use --skip-cb if you already have a prepared CB working directory and want to reuse it without rebuilding:
`python auto-calibration.py --pipeline cb --cb-workdir 'path-to-directory' --skip-cb`

#### Running auto-image
After CB calibration is submitted, the pipeline can chain auto-image automatically. You can also run auto-image manually on an existing .ms path:
`python auto-calibration.py --pipeline auto-image --asc-ms-path 'path-to-directory'`

### Running ASC
For ASC:
`python auto-calibration.py --pipeline asc --url 'your-link-goes-here'`

If it is ASC on A-config, use --a-config. This adjusts L/S band resources to reduce memory-related crashes, but those bands can still fail on difficult datasets.
`python auto-calibration.py --pipeline asc --url 'your-link-goes-here' --a-config`

If you already ran CB and now want ASC, point to the directory instead of giving a URL:
`python auto-calibration.py --pipeline asc --asc-ms-path 'path-to-directory'`

### Running CB-ASC
You can chain CB then ASC on the same dataset. Supply an SDM-BDF source link (or other valid CB input):
`python auto-calibration.py --pipeline cb-asc --url 'your-link-goes-here'`

## In Progress (Check status)
This builds a working directory named:
- ASC.projectname.objectname.observationdate
- CB.projectname.objectname.observationdate

Depending on dataset size, downloads can take a while. Keep your terminal open until submission completes.

Check running jobs with:
`squeue -l --me`

For more detail:
`sacct -u nm-XXXXX --format=NodeList,JobID,JobName%90,State,Start,End`

CB usually finishes within a day for most dataset sizes. ASC can take significantly longer depending on config and can run into memory issues for larger runs.

## Completed
You will not receive a completion notification by default, so check job status to confirm completion or failure.

#### CB
Inside a completed CB.* directory, calibration should produce the .ms output. Auto-image outputs are produced by the follow-up auto-image-VLA job (when enabled) and include frequency images and fit result CSV outputs.

#### ASC
Inside a completed ASC.* directory, final outputs are placed under final_files, including ASC images and fit CSV files. It is not uncommon for lower frequencies to fail; if expected files are missing, those splits likely did not complete.

### Getting it off the Cluster
To copy data off the cluster, first find your path on the cluster with `pwd`. Then from a local terminal (not logged into cluster), run something like:
`scp -r nm-XXXXX@guest-login.aoc.nrao.edu:/lustre/aoc/observers/nm-XXXXX/auto_selfcal_cluster/ASCorCB.directory/final_files/ ~/where/ever/you/want`

The first path is where the data is on the cluster, and the second path is where you want it locally.

## Logs
Before/after runs, metadata snapshots and Slurm .out/.err artifacts are moved/grouped under logs. If something breaks or crashes, check those files first. The scripts are set up to throw useful setup/runtime errors, but they will not catch everything.

If something breaks, run `git pull` to make sure you are on the latest version and try again.

