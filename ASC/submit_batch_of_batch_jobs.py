import os
import subprocess
import time

# Path to the file containing the list of batch scripts
batch_list_file = 'batch_files_list.txt'

# Open and read each line
with open(batch_list_file, 'r') as f:
    for line in f:
        script_path = line.strip()
        if script_path and os.path.exists(script_path):
            try:
                print(f"Submitting: {script_path}")
                subprocess.run(['sbatch', script_path], check=True)
                time.sleep(10)
            except subprocess.CalledProcessError as e:
                print(f"Failed to submit {script_path}: {e}")
        else:
            print(f"Script does not exist or is empty: {script_path}")
