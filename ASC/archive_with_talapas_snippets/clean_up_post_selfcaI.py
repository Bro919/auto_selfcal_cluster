import shutil
import os
from pathlib import Path
import os

# user options
root_dir = "/gpfs/projects/nova/jimmy/test_splitting"
prefix_string = "24A-322.ASASSN-14ae.2024-08-08"
apply_calibrations = True
concat_final_ms = True

# stick all final files in final_image folder
frequencies = [1.25, 1.5, 1.75, 
               2.5, 3.0, 3.5, 
               5.0, 6.0, 7.0, 
               9.0, 10.0, 11.0]
bands = ["EVLA_L", "EVLA_L", "EVLA_L", 
         "EVLA_S", "EVLA_S", "EVLA_S",
         "EVLA_C", "EVLA_C", "EVLA_C", 
         "EVLA_X", "EVLA_X", "EVLA_X"]

final_files_directory = f"{root_directory}/final_files"
os.mkdir(final_files_directory)

list_of_mses = []
for i in range(len(frequencies)):

    freq = frequencies[i]
    band = bands[i]
    
    working_directory = f"{root_dir}/{freq}GHz"
    final_string = f"{band}_final"

    source_dir = Path(working_directory)
    destin_dir = Path(f"{final_files_directory}/{freq}GHz")
    destin_dir.mkdir(exist_ok=True)

    final_files = [p for p in source_dir.rglob("*") if final_string in p.name]

    print(f"Moving {len(final_files)} final files to {destin_dir}") 
    for ff in final_files:
        destination = destin_dir / ff.name
        if ff.is_file():
            shutil.copy2(ff, destination)
        elif ff.is_dir():
            shutil.copytree(ff, destination, dirs_exist_ok=True) 
    print("Done")

    # apply calibrations to each measurement set
    if apply_calibrations:
        print("Applying calibrations to original ms")
        execfile(f"{working_directory}/applycal_to_orig_MSes.py")
        print(f"Done applying calibrations for {freq}")

    original_ms = f"{prefix_string}.{band}.{freq}GHz_target.ms"
    list_of_mses.append(original_ms)

# concat into single ms
if concat_final_ms:
    print("Creating final_selfcal measurement set")
    final_ms_path = f"{root_dir}/{prefix_string}.auto_selfcal.final.ms"
    
    # check if it exists first:
    if not os.path.exists(final_ms_path):
        concat(vis=list_of_mses, concatvis=final_ms_path)
        print(f"Created final self_cal ms {final_ms_path}")
    else:
        print(f"Final self_cal ms already exists at {final_ms_path}")
    
    # move to final images
    source_file = Path(final_ms_path)
    destination_dir = Path(final_files_directory)
    destination_dir.mkdir(parents=True, exist_ok=True)
    if not os.path.exists(str(destination_dir / source_file.name)):
        shutil.move(str(source_file), str(destination_dir / source_file.name))
        print(f"Moved final self_cal ms to final_files directory")





             

# 