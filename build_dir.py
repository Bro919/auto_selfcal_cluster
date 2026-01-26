import argparse 
from pathlib import Path
import shutil
import tarfile
import sys
import urllib.request
from datetime import date

def download_progress(blocks, block_size, total_size):
    if total_size <= 0:
        return
    downloaded = blocks * block_size
    percent = min(downloaded / total_size * 100, 100)\
        
    mb_done = downloaded / (1024 * 1024)
    mb_total = total_size / (1024 * 1024)

    print(
        f"\rDownloading: {percent:5.1f}% ({mb_done:6.1f} MB / {mb_total:.1f} MB)",
        end='',
        flush=True
    )

def main():
    parser = argparse.ArgumentParser(
        description="Download a tar file, extract it, and move a specified file to a new location, and create a working directory."
    )

    parser.add_argument("project_code", help="Name of the project code, to name the working directory")
    parser.add_argument("object_name", help="Path to the working directory")
    parser.add_argument("url", help="URL of the tar file to download")
    parser.add_argument("asc", help="Path to the ACS directory")

    args = parser.parse_args()

    today = date.today().isoformat()
    workdir_name = f"build({args.project_code}).{args.object_name}.{today}"
    workdir_path = Path(workdir_name)

    # Create working directory
    workdir_path.mkdir(parents=True, exist_ok=True)

    # Download the tar file
    tar_name = f"build({args.url})"
    tar_path = workdir_name / tar_name

    print(f"Downloading {args.url}")
    urllib.request.urlretrieve(args.url, tar_path, reporthook=download_progress)
    print("\nDownload complete.")
    
    # Extract the tar file
    with tarfile.open(tar_path, "r:*") as tar:
        tar.extractall(path=workdir_path)

    # Find extracted directory
    extracted_dirs = [p for p in workdir_name.iterdir() if p.is_dir() and p.name != args.template]

    if len(extracted_dir) != 1:
        print("Error: Expected exactly one extracted directory.")
        
    extracted_dir = extracted_dirs[0]

    # Copy asc directory
    template_src = ASC / args.asc
    template_dst = workdir_name / args.asc

    if not template_src.exists():
        sys.exit(f"Error: ACS directory {template_src} does not exist.")

    shutil.copytree(template_src, template_dst, dirs_exist_ok=True)

    # Move extracted directory to the working directory
    final_dir = Path(workdir_name)
    shutil.move(extracted_dir, final_dir)

    print(f'Final working directory created at: {final_dir.resolve()}')
    print("Process completed successfully.")

if __name__ == "__main__":
    main()