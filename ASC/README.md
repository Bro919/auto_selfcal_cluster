# Run automatic self-calibration on NRAO cluster 
Credit to Patrick Sheehan (https://github.com/psheehan/auto_selfcal) for developing the auto_selfcal code package itself. My code below is simply designed to streamline running auto_selfcal on clusters we have access to at UO and NRAO. 

(TODO) NOTE: this code can be tweaked to run on Talapas with the following changes with respect to filesystem and SLURM scheduler options.

## Best uses for auto_selfcal
I have found auto_selfcal to be good at...
* Cleaning signal from off-center bright sources in FOV
* Improving point-source shapes to look more beam-like
* Producing clean noise pattern free of patches near source
* Achieving low RMS. Ex: the following RMS values are achieved from 2hr SEDs with strong source signal: 15-40 uJy in L-band, 10-35 uJy in S-band, 20-40 uJy in C-band, and 20-35 uJy in X-band.

If your image is already decent quality around your source location, it will not dramatically change the flux values and RMS levels you'll report, though it may visually improve the image. However, if you have a wonky SED, it's worth trying out.

## How auto_selfcal works and why my scripts use it impractically
Patrick Sheehan's auto_selfcal (https://github.com/psheehan/auto_selfcal) solves for a range of calibration solutions using different solution intervals and applies the best-fit ones to the measurement set. It then creates a final image for you using the self-cal measurement set. It has capability to do a multi-frequency .ms for an SED but it would realistically require running in parallel using mpicasa, which I have found to error on both Talapas and NRAO. Also, you'll miss out on getting split-band images if you self-cal the entire SED unless you then apply the calibrations to create the _final.ms and then re-image the _final.ms yourself. That is probably a good thing to work out at some point, but it seemed like extra steps. 

Here's the workaround that I've adapted: split your .ms into the half-bands and then submit separate batch jobs for each. This in theory solves two issues: a) you get automatic split-band final images from the auto_selfcal script without having to re-image from the _final.ms and b) you can submit several of these split-band auto_selfcal jobs at the same time, effectively running an entire SED worth in 8-12 parallel jobs. 

## Other notes
* This takes up a LOT of storage space! Running auto_selfcal on an A-config SED will produce about 2 TB of data over the course of the job. Some of this is from tclean's temp lattices that are deleted afterwards, but you still will have to clean up your directory on NRAO afterwards, and you will not be able to run on Talapas if you only have the default storage quota. I have a script to clean things up for you.
* Low-frequencies at A-config take forever to run (sometimes timing out after a week) and produce large (~2GB) _final.* files. I'm yet to establish the trend exactly. Consider this before running auto_selfcal on SEDs taken at A config.

## Repository contents:
1. prep-ms-for-auto-selfcal.py: Script to prep your measurement set in the current working directory for auto_selfcal. It first splits the main.ms file into main_target.ms. Then it splits the main_target.ms by spectral windows based on the user-specified split_bands command and creates a sub-directory of {freq}GHz/ for each frequency in your requested splits. This directory is where auto_selfcal will write all the files for that given split ms. Finally, it writes batch files to perform auto_selfcal on each of these split measurement sets and saves the batch file paths to a text file. No auto_selfcal will be done by running this script: it just sets up batch scripts.
2. submit_batch_of_batch_jobs.py: Simple script to submit all the batch jobs that prep-ms-for-auto-selfcal.py wrote.
3. clean_up_post_selfcal.py: Script to consolidate the _final files from each {freq}GHz/ subdirectory into one called final_files that can then be easily secure copied to your local system. You can choose whether you want just the images, the other tclean objects like model and residual, or the entire re-concatenated self-cal _final.ms.
4. vla-configuration-schedule.csv: table from https://science.nrao.edu/facilities/vla/proposing/configpropdeadlines
5. vla-resolution.csv: table from https://science.nrao.edu/facilities/vla/docs/manuals/oss/performance/resolution

## Getting started with GitHub
To obtain a local copy of this code + its supporting materials, clone the repository in Terminal via


    git clone https://github.com/jlynch2195/auto_selfcal_cluster.git

You only have to do this once. After some time, it's good to check the status to see if there's a) been an update on my end or b) been some changes on your end:

    git status

To update your local copy to match the newest version on GitHub, make sure you're in the repository in your filesystem, then run

    git pull

You may get error/warning messages about needing to commit changes before pulling, meaning you've made edits to the existing files and git doesn't want to override those. If you want to keep your version, you can rename yours to avoid overwriting them. There's probably better practice; it's worth a Google.

## Getting familiar with the NRAO cluster
Request an account: https://info.nrao.edu/computing/guide/cluster-processing/user-accounts. Someone will email you a username of form nm-YYYYY. Your account comes with 5TB of storage and a 1TB grace amount with a grace period of 1 week. 

Login with

    ssh nm-YYYYY@ssh.aoc.nrao.edu

This puts you on a login node in your home directory. To start computing, login to the master node:

    ssh nmpost-master

Before you run tclean or any scripts, you have to check out an interactive node:

    nodescheduler -r 3 # requests time for 3 days

Check to see which interactive node you were given:

    squeue -l --me

This will print a node number under the nodelist, as in nmpostZZZ. Again, login to this node:

    ssh nmpostZZZ

Now you can start running the auto_selfcal scripts. 

## Get familiar with nano
The text editor "nano" is how you're going to edit code on the cluster, since command line access is the easiest way to use the NRAO cluster (at least to me). To try it out, move to where you want all your files to go (for me, that's ~/Desktop) and make a file named test.txt. This will bring up a blank file with lots of keyboard actions on the bottom

    cd ~/Desktop
    nano test.txt

Type whatever you want and save with CTRL X, then y, then ENTER. You can check to see if your changes went through: this will print the contents of test.txt to the terminal:

    cat test.txt

There are probably options to utilize a graphical user interface with the NRAO cluster but this has worked for me so far. Just takes some getting used to.

## Get your measurement set to cluster
It's about 10 times faster (than the method below) if you just request the data from the NRAO archive and then use the wget command from the email directly in your home directory on the NRAO cluster.

However, if you have a .ms locally that you wish to copy over, open up a new terminal window on your local machine. Now copy your measurement set to your home directory on NRAO:

    scp -r ~/path/to/measurement_set.ms nm-14416@ssh.aoc.nrao.edu:~/Desktop

This should take about 30mins for a 1hr C-band ms file. 

Once that's done copying, login to NRAO and check to make sure it make it there:

    cd ~/Desktop
    ls

Check to make sure everything got copied over:

    cd measurement_set.ms
    ls

I've had issues with the table.dat files not making it and that breaks everything. If you're missing table.dat, you can try to continue, but know that you may get an error. If so, the path of least resistance is to delete the ms on the cluster and re-upload it. If you're also missing table.dat from your local copy, you'll need to re-download the ms from the NRAO archive.

It's probably not required, but you want the file system to be ~/Desktop/project_code/project_code.source_name.YYYY-MM-DD/project_code.source_name.YYYY-MM-DD.ms, so set that up via

    cd ~/Desktop/project_code/
    mv ~/Desktop/project_code/old_folder_name ~/Desktop/project_code/project_code.source_name.YYYY-MM-DD  # the old folder name is something like "pipeline..." if you did wget
    cd ~/Desktop/project_code/project_code.source_name.YYYY-MM-DD
    mv ~/Desktop/project_code/project_code.source_name.YYYY-MM-DD/old_ms_name.ms ~/Desktop/project_code/project_code.source_name.YYYY-MM-DD/project_code.source_name.YYYY-MM-DD.ms

Now your filesystem is setup to be compatible with how I've written the scripts.

## Set-up Part 1: Do this only once, ever!
__Super important__: this part takes some care and is vital to things working correctly!!! You'll need two sets of files: the auto_selfcal github repo, and my auto_selfcal_cluster repo, which you can clone into your Desktop via

    cd ~/Desktop
    git clone https://github.com/jlynch2195/auto_selfcal_cluster.git
    git clone https://github.com/psheehan/auto_selfcal.git

The files in auto_selfcal_cluster need to know where the auto_selfcal repo is. So, you'll have to edit line 194 in my prep-ms-for-auto_selfcal.py script:

    cd auto_selfcal_cluster
    nano prep-ms-for-auto_selfcal.py
    # edit auto_sc_files_directory = "/lustre/aoc/observers/nm-14416/Desktop/auto_selfcal" to be your username nm-YYYYY or wherever you decided to clone auto_selfcal repo
    # save with CTRL X, then y, then ENTER

You'll also need to edit your username into a couple of other places: line 9 in install_pandas.py, and line 7 in clean_up_post_selfcal.py. Do these with nano as just above.

## Set-up Part 2: Do this for every new .ms!
The auto_selfcal repo will live untouched in the location you wrote it. However, the scripts in the auto_selfcal_cluster folder need to be copied over into each observation folder directory and edited there to change things like the .ms name, frequencies, and so on. This makes version control somewhat challenging because you're not copying the repo itself, just the files in it, so you miss out on history. Copy over all the files from auto_selfcal_cluster:

    cp -r ~/Desktop/auto_selfcal_cluster/* ~/Desktop/project_code/project_code.source_name.YYYY-MM-DD

Move into your ~/Desktop/project_code/project_code.source_name.YYYY-MM-DD directory and list the files there with ls. You should see:

    project.source_name.YYYY-MM-DD.ms  prep-ms-for-auto-selfcal.py  submit_batch_of_batch_jobs.py  install_pandas.py   vla-configuration-schedule.csv  vla-resolution.csv

The only file you need to edit is prep-ms-for-auto-selfcal.py. Copy the name of measurement_set.ms before opening nano and make sure you're in your project_code.source_name.YYYY-MM-DD directory

    nano prep-ms-for-auto-selfcal.py

Now edit the required fields after the imports directly in the file: I removed the config.yaml file because it was too much to keep track of. One argument is "split_band" which can be "whole" to use all the spws for the band to make 1 image, "halves" to use half of the spws to make 2 images, or "both" to do both. For example, for C-band, "whole" makes an image for 6 GHz, "halves" makes 5 and 7 GHz, and "both" makes 5, 6, and 7 GHz. For a single C-band measurement set, I usually just keep it as "whole" to get a 6 GHz image. Arguments use_single_band and single_band should be set if using a single frequency measurement set.

    measurement_set = "25A-060.AT2019qiz.2025-06-01.ms"   
    source_name = "AT2019qiz"                          # needs to match name in listfile
    split_band = "whole"                               # can be "whole" (ex: 6 GHz), "halves" (5 GHz and 7 GHz), or "both" (5, 6, and 7 GHz)
    use_single_band = False                            # toggle true for single-freq or an SED where you only want one band
    single_band = "EVLA_C"                             # if use_single_band, specify band
    use_single_freq = False                            # idk if this works or why it's even in here so just leave it alone
    single_freq = 9

Once done editing, remember how to save: CTRL X, then y, then ENTER. You can check to make sure changes took place if you want:

    cat prep-ms-for-auto-selfcal.py

## Actually run auto_selfcal
__Important__: before running any code, you need to make sure you're on an interactive node. Once you are, open up casa

    casa

The age-old "no module named pandas" error is fixed and wrapped up in the install_pandas.py file in this repo, so run that first. It will give some red text that looks like an error but it actually works:

    execfile("install_pandas.py")

Now run the prep-ms script:

    execfile("prep-ms-for-auto-selfcal.py")

This will take about 2 minutes per split that you requested, so up to half an hour for LSCX SEDs running "both" splits like I usually do. 

As mentioned in the "repository contents" section, no auto_selfcal actually occured after running the prep script! It just outputs a bunch of batch scripts that will be submitted as batch jobs that run auto_selfcal on each split. A batch job is basically an untouchable compute task that will run for some amount of time before either crashing or finishing. I am not an expert on them and there are better practices for how I've set this up. To submit each of these batch scripts as a job, run

    execfile("submit_batch_of_batch_jobs.py")

You should see a list of logs print like this:

    Submitting: 1.25GHz/auto_selfcal_project.source.YYYY-MM-DD.EVLA_L.1.25GHz_target.sh
    Submitted batch job 3526940
    Submitting: 1.5GHz/auto_selfcal_project.source.YYYY-MM-DD.EVLA_L.1.5GHz_target.sh
    Submitted batch job 3526940
    ...

All this means is that the jobs to run auto_selfcal on each split have been submitted to the scheduler. They might be queued (that's fine) but once they're running, there's no guarentee that they'll complete, and you won't get notified if they fail (there's ways to get an email but I haven't implemented them yet). The best way to check the status of your jobs is to run:

    sacct -u nm-YYYYY --format=NodeList,JobID,JobName%90,State,Start,End

There are a few statuses:
* __Completed__: cd into the split directory and list the files with ls. You should see a bunch of files, with a subset of them being named _final.image.tt0 and so on. That means it completed successfully.
* __Failed__: (or for those that completed but there are not _final files) print (using "cat") the .out and .err files to see if you can identify what went wrong. "OOM" means out of memory, which has been the most common error thus far. To fix that, you can edit line 255 in prep-ms-for-auto_selfcal.py (#SBATCH --mem=128G) to change the memory limits. 128GB is already a ton though, so I don't have much guidance there.
* __Running__: you can vibe check the progress by just seeing how many solution intervals the script has completed already. I believe it starts with large solution intervals and works down, such that the order of files you should see is something like dirty > initial > inf_EB > inf > As > Bs > int. If you see double digit seconds (like 42.00s) you're almost there.

## Get the results back locally
I find it easiest to wait until every split is done running to consolidate results and transfer them locally. Once all the splits are done, the clean_up_post_selfcal.py script will put everything you want into a final_files folder. Edit it with nano to get the results you want:

    root_dir = "/lustre/aoc/observers/nm-YYYYY/Desktop/23A-241/23A-241.ASASSN-14ae.2023-09-17"
    prefix_string = "23A-241.ASASSN-14ae.2023-09-17"
    final_images_only = True                                 # toggle False if you also want the model, residual, etc. that tclean gives 
    apply_calibrations = True                                # if you only want the tclean results, set to False. This will apply calibrations to each split measurement set
    concat_final_ms = True                                   # if you only want the tclean results, set to False. This will concat all split measurement sets into one _final.ms with calibrations applied
    
Then run it with

    execfile("clean_up_post_selfcal.py")

Given unlimited time and storage, I'd recommend applying the calibrations and concating the measurement set so you can store the self-cal measurement set and you won't need to redo this process on that data again (at least, provided you can independently image the self-cal ms and get the same images you received during the auto_selfcal process). However, they can be large and sometimes you're pressed for time. If you elected to apply calibrations and concat the final measurement set, expect clean_up_post_selfcal.py to take about as long as it did to run prep-ms-for-auto_selfcal.py. If you opted for just the images or tclean products, it should only take a few minutes. 

Once you have the final_files folder, copy it locally to your latop by opening a local terminal window and running

    scp -r nm-YYYYY@ssh.aoc.nrao.edu:~/Desktop/project_code/project_code.source_name.YYYY-MM-DD/final_files ~/local_Desktop/where_you_want_the_final_files_folder

And you have the entire SED with automatic self-calibration applied, with final split-band images, without ever having to do self-cal yourself! See below for some post-processing suggestions.

## Post-processing options  
My other repositories contains scripts for extracting flux values from point-source fits and creating 128x128 snapshot FITS images for easy quick-look:

    git clone https://github.com/jlynch2195/auto-image-VLA.git
    git clone https://github.com/jlynch2195/archive-ltr.git

* The auto-image-VLA/run_fit_point_source.py file takes in a list of images and fits a point source at the center of each image, returning detailed reports about the fits and writing region files for viewing in CARTA.
* The archive-ltr/prep_snapshots.py file takes in a list of images and returns 128x128 (or NxM) snapshots

TODO: The basic idea is that once one of us deems a data set "publishable", we can push the flux values and snapshots to the archive-ltr for safekeeping and for general use in the group.
