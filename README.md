# RUNNING INITIAL CALIBRATION OR AUTO SELF-CALIBRATION
Many of the inital Auto-Selfcal scripts are forked off of the work done by Jimmy Lynch (https://github.com/jlynch2195/auto_selfcal_cluster) and also his auto-image-VLA (https://github.com/jlynch2195/auto-image-VLA) as a submodule. As mentioned by Jimmy also use the auto selfcal code developed by Patrick Sheehan (https://github.com/psheehan/auto_selfcal) credit goes to them for the basis of this project. Unlike in Jimmy's project Patrick Sheehan's work is installed as a submodule meaning no need to extra installation steps. This project also makes use of the casa calibration pipeline script supplied by the NRAO.
This is setup to be an automation wrapper for their code, making it easier to start calibration/self-calibration jobs with the use case of the NRAO cluster and Talapas specifically in mind.
My main use case has been on the NRAO cluster, read through Jimmy's repo to get an idea of how to request access and make basic use of the cluster. He also comments on best use cases and how his scripts make use of the work from Patrick Sheehan. I would recommend fully reading through Jimmy's README before this one as I will likely skip over many of the points that he makes. If this has become Jimmy's README.md his original one is inside of my ASC directory so you can still find it if you need to.

## Making use of auto-calibration
The main wrapper that you should be using is the auto-calibraiton.py in the main directory. It calls other scripts and wrappers that are in the Auto-SelfCal (ASC), Calibration (CB) and runtime directories. Where it downloads and sets up a main working directory, prepares the data and submits the slurm job to a node. Being able to deal with both SDM-BDF dataset for inital calibration (CB) to create a .ms directroy, running a Auto-SelfCal (ASC) on an already create .ms directory, or if already predetermined CB directly into ASC. 
auto-calibration has lots of extra flags and parameters that can be used to customize how it's ran. Please leave them at default unless you know what you are doing. I will list some possibly useful ones at the bottem of the README.

# Setup
Since I have mostly done this project on the Cluster that is what I will default to when talking about getting auto-cal to work.
You'll need to request an account access with NRAO to get into the cluster. They will give you a nm member number that you will use to login to the cluster.
Then you just open your terminal and use `ssh nm-XXXXX@guest-login.aoc.nrao.edu` to login using the password that you set for your NRAO account.

### OS consideration
One important consideration when you are connecting to the cluster is what OS your computer is running. If you're using MacOS you should have no issues as your terminal is already set to use bash. If you're using Linux you'll be fine you don't need my help. 
If you're on Windows you'll need to make use of PuTTy or you can use WSL. I prefer WSL but either can allow you to connect to the Cluster. They are both pretty straight forward to install and get going but make sure to use Ubuntu if you're using WSL. Once you have PuTTy or WSL setup and running you should get a bash terminal open.

## Installing the repo
After you have logged in use `ssh nmpost-master` to move to the master node and request an interactive node to run code off `nodescheduler -r 3 # requests 3 days`. You'll need todo this anytime that you run auto-calibration or any other code on the cluster, and try not to request too much time and hog the nodes as only one person can use them interatctivly at a time. Then run `squeue -l --me` to see the node that was given and use `ssh nmpostXXX` to move over.
Then go to you'r main directory with `cd` and clone the repo:
`git clone --recurse-submodules https://github.com/Odyia/auto_selfcal_cluster`
If you already cloned normally without all the submodules then run:
`git submodule update --init --recursive`
You might have to `cd` into the directory to run the git command.

## Contents
As I said earlier you should really only be using the auto-calibration wrapper but the other main wrappers and scripts are in runtime. The CB and ASC specifc scripts for running on the data are in their respective directories. The logs directory will collect slurm and metadata outputs from jobs to keep the main directory cleaner and all the submodules are stored in the repo directory.

## Requesting Data
You can run this code using local data I will go over how to do that later but most commonly you will run auto-calibration with a url from the NRAO archive (https://data.nrao.edu/portal/#/). Make sure to login with your NRAO account to have access to your data. Depending on whether you are running CB or ASC you'll need to request either SDM-BDF (CB) or a Calibrated Measurement set (ASC). They will process your request and email you with a link to the directory.

# Running auto-calibration
After you have requested your data and received the link you can run auto calibration.

!VERY IMPORTANT! 
ASC CAN CREATE 12 SLURM JOBS THAT CAN TAKE 7-10 DAYS ON A-CONFIG SO DON'T RUN MORE THAN ONE DATASET AT A TIME, AND BE SURE TO CONFIRM IT'S BEEN COMPLETED.
CB will only run 2 jobs and be usually done within the day, it's ok to run a few of them.

To run enter the directory `cd auto_selfcal_cluster/`

### Running CB
If it's CB:
`python auto-calibration.py --pipeline cb --url 'your-link-goes-here'`
If you manually moved the SDM-BDF into the directory you can run it without a link like this:
`python auto-calibration.py --pipeline cb --cb-workdir 'path-to-directory'`

#### Running auto-image
After CB is completed it will automatically run Jimmy's auto-image-VLA, making an images for the frequencies and an overall im-fit.csv, but you can also manually run this on a .ms you have in the directory using:
`python auto-calibration.py --pipeline auto-image --asc-ms-path 'path-to-directory'`

### Running ASC
If it's ASC:
`python auto-calibration.py --pipeline asc --url 'your-link-goes-here'`
If it's ASC on a-config then use the --a-config flag, it sets lower frequency bands to run a bit slower reducing the chance that they crash due to low memory, but they will more than likely crash anyway.
`python auto-calibration.py --pipeline asc --url 'your-link-goes-here' --a-config`
If you ran CB and now want to ASC it, you can point to the directory rather than giving a link
`python auto-calibration.py --pipeline asc --asc-ms-path 'path-to-directory'`

### Running CB-ASC
You can also set them up to chain, where it runs cb then asc on the dataset one after the other, while being sure to supply a SDM-BDF link or using --cb-workdir
`python auto-calibration.py --pipeline cb-asc --url 'your-link-goes-here'`

## In Progress (Check status)
This will then cause it to download and build the working directory denoted by ASC.'projectname'.'objectname'.'observationdate' or CB.'projectname'.'objectname'.'observationdate' respectively. Depending on how large the dataset is it could take a while to download and the terminal must stay open during the whole process til the job is submitted.
You can check if the jobs are running with `squeue -l --me` as long as you're still on an interactive node. This will give you a basic look at what is running. If you want more details you can run:
`sacctu`

As I said earlier CB will usually finish within a day no matter the dataset size. Whereas for ASC Depending on the config it could take a while to complete. With the sacctu command you can see how long it has been running, how much time it has left before its stopped and the name of the job. You'll likely never to look at this unless you are running ASC since it's more computationally intensive and can run out of memory when dealing with larger configs.

## Completed
You won't receive a notification when the jobs are completed, you will have to check their status to see when they are done or if they have broken. I might at some point look into sending an email when a job is completed.

#### CB
Inside the completed CD.* directory will be the finished .ms of your datset as well as 512x images for each of the frequencies. Along with these frequency images you'll also get the imfit.csv with peak fluxes and other data about the images.

#### ASC
Inside the completed ASC.* directory will be the final_files directory that will have the ASC images aswell as the imfit.csv files as well. It is not uncommon for lower frequencies to fail the ASC so if their is nothing in the folder then it failed to complete.

### Getting it off the Cluster
To get your data off the cluster, first you need to know where it is on the cluster with `pwd`. Then open a local terminal without connecting to the cluster and run something like:
`scp -r nm-XXXXX@guest-login.aoc.nrao.edu:/lustre/aoc/observers/nm-XXXXX/auto_selfcal_cluster/ASCorCB.directory/final_files/ ~/where/ever/you/want`
First bit is where on the cluster is it and the second is for where on your computer do you want to put it.

## Logs
Before and after every run metadata temp files and the slurm job .out and .err files will be moved out of the main directory into logs. If something breaks, crashes or goes wrong it'll be in those .err and .out files. Look there to see what went wrong and if it's a simple error. The scripts are setup to throw errors if they detect something while they are setting up but they won't find everything.
If something does break be sure to run `git pull` so that you are using the most recent version of the repo and try again.

