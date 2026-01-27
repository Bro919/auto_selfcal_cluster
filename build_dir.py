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

    # Check for existing tar files in current directory
    cwd = Path.cwd()
    tar_files = list(cwd.glob("*.tar*"))
    
    if tar_files:
        # Use the first tar file found
        tar_path = workdir_path / tar_files[0].name
        print(f"Found tar file: {tar_files[0].name}")
        shutil.copy(str(tar_files[0]), str(tar_path))
        print("Copied to working directory.")
    else:
        # Download the tar file
        tar_name = Path(args.url).name
        tar_path = workdir_path / tar_name
        print(f"Downloading {args.url}")
        urllib.request.urlretrieve(args.url, str(tar_path), reporthook=download_progress)
        print("\nDownload complete.")
    
    # Verify the tar file exists and is valid
    if not tar_path.exists():
        sys.exit(f"Error: Tar file was not downloaded successfully at {tar_path}")
    
    # Check if file is a valid tar archive
    if not tarfile.is_tarfile(str(tar_path)):
        sys.exit(f"Error: Downloaded file at {tar_path} is not a valid tar archive. The download may have been incomplete or corrupted.")
    
    # Extract the tar file
    try:
        with tarfile.open(str(tar_path), "r:*") as tar:
            tar.extractall(path=workdir_path)
    except tarfile.ReadError as e:
        sys.exit(f"Error: Failed to extract tar file: {e}")

    # Find extracted directory
    extracted_dirs = [p for p in workdir_path.iterdir() if p.is_dir() and p.name != args.asc]

    if len(extracted_dirs) != 1:
        print("Error: Expected exactly one extracted directory.")
        
    extracted_dir = extracted_dirs[0]

    # Copy asc directory
    template = args.asc
    template_src = Path.cwd() / template
    template_dst = workdir_path / template

    if not template_src.exists():
        sys.exit(f"Error: ACS directory {template_src} does not exist.")

    shutil.copytree(template_src, template_dst, dirs_exist_ok=True)

    # Move extracted directory to the working directory
    final_dir = workdir_path
    shutil.move(str(extracted_dir), str(final_dir))

    print(f'Final working directory created at: {final_dir.resolve()}')
    print("Process completed successfully.")

if __name__ == "__main__":
    main()