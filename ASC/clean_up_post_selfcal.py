import argparse
import shutil
import os
from pathlib import Path
import re

def get_frequencies_from_dirs(root_dir):
    """
    Scans root_dir for subdirectories ending with 'GHz', extracts the numeric frequency values, and returns them as floats.
    """
    freq_list = []
    for entry in os.listdir(root_dir):
        full_path = os.path.join(root_dir, entry)
        if os.path.isdir(full_path) and entry.endswith('GHz'):
            # Extract the numeric part
            match = re.match(r"([\d.]+)GHz", entry)
            if match:
                freq_list.append(float(match.group(1)))
    return sorted(freq_list)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Collect final files from frequency folders into a final_files directory."
    )
    parser.add_argument(
        "root_dir",
        nargs="?",
        default=None,
        help="Root observation directory containing <freq>GHz folders. Defaults to current working directory.",
    )
    parser.add_argument(
        "--prefix",
        default="",
        help="Prefix string used only if applying calibrations or concatenating final measurement sets.",
    )
    parser.add_argument(
        "--all-final-products",
        action="store_true",
        help="Copy all final products instead of only the final tt0 image.",
    )
    parser.add_argument(
        "--apply-calibrations",
        action="store_true",
        help="Apply calibrations to each split measurement set.",
    )
    parser.add_argument(
        "--concat-final-ms",
        action="store_true",
        help="Concat all split measurement sets into one final measurement set.",
    )
    return parser.parse_args()


args = parse_args()
# Normalize once so later path operations always use pathlib semantics.
root_dir = Path(args.root_dir or os.getcwd())
root_dir = Path(root_dir).expanduser()
prefix_string = args.prefix
final_images_only = not args.all_final_products
apply_calibrations = args.apply_calibrations
concat_final_ms = args.concat_final_ms

if not root_dir.is_dir():
    raise FileNotFoundError(
        f"root_dir does not exist: {root_dir}.\n"
        "Please run the script from the observation root or pass the correct path."
    )

# for an SED
#frequencies = [1.26, 1.52, 1.75,
#               2.5, 3.0, 3.5,
#               5.0, 6.0, 7.0,
#               9.0, 10.0, 11.0]
bands = ["EVLA_L", "EVLA_L", "EVLA_L",
         "EVLA_S", "EVLA_S", "EVLA_S",
         "EVLA_C", "EVLA_C", "EVLA_C",
         "EVLA_X", "EVLA_X", "EVLA_X"]

# for a single frequency
# frequencies = [6.0]
# bands = ["EVLA_C"]

# frequencies will be set dynamically
frequencies = get_frequencies_from_dirs(root_dir)

final_files_directory = f"{root_dir}/final_files"
os.makedirs(final_files_directory, exist_ok=True)

list_of_mses = []
for i in range(len(frequencies)):

    freq = frequencies[i]
    band = bands[i]
    
    working_directory = f"{root_dir}/{freq}GHz"
    if final_images_only:
        final_string = f"{band}_final.image.tt0"
    else:
        final_string = f"{band}_final"
    source_dir = Path(working_directory)
    destin_dir = Path(f"{final_files_directory}/{freq}GHz")
    destin_dir.mkdir(exist_ok=True)

    final_files = [p for p in source_dir.rglob("*") if final_string in p.name]

    print(f"Moving {len(final_files)} final files to {destin_dir}") 
    def copy_tree_compat(src, dst):
        if dst.exists():
            if dst.is_file():
                dst.unlink()
            else:
                shutil.rmtree(dst)
        shutil.copytree(src, dst)

    for ff in final_files:
        destination = destin_dir / ff.name
        if ff.is_file():
            shutil.copy2(ff, destination)
        elif ff.is_dir():
            copy_tree_compat(ff, destination)
    print("Done")

    # apply calibrations to each measurement set
    if apply_calibrations:
        print("Applying calibrations to original ms")
        os.chdir(working_directory)
        execfile(f"{working_directory}/applycal_to_orig_MSes.py")
        print(f"Done applying calibrations for {freq}")
        os.chdir(root_dir)

    original_ms = f"{working_directory}/{prefix_string}.{band}.{freq}GHz_target.ms"
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
