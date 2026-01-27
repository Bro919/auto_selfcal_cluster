import argparse 
from pathlib import Path
import shutil
import tarfile
import sys
import urllib.request
from datetime import date
import re

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

# Use ignore_errors to handle any permission issues
def copy_tree(src, dst):
    src = Path(src)
    dst = Path(dst)
    
    # Skip if source and destination are the same
    if src.resolve() == dst.resolve():
        print(f"Skipping copy: source and destination are the same ({src})")
        return
    
    if not dst.exists():
        dst.mkdir(parents=True)
    for item in src.iterdir():
        src_item = src / item.name
        dst_item = dst / item.name
        
        # Skip if source and destination are the same
        if src_item.resolve() == dst_item.resolve():
            continue
        
        if src_item.is_dir():
            if dst_item.exists():
                shutil.rmtree(str(dst_item))
            shutil.copytree(str(src_item), str(dst_item), ignore_dangling_symlinks=True)
        else:
            shutil.copy2(str(src_item), str(dst_item))

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
        
        # If URL ends with /, it's a directory - need to find tar file inside
        if args.url.endswith('/'):
            print(f"Fetching directory listing from {args.url}")
            try:
                with urllib.request.urlopen(args.url) as response:
                    html = response.read().decode('utf-8')
                    # Extract tar file links from HTML
                    tar_links = re.findall(r'href=["\']([^"\']*\.tar[^"\']*)["\']', html)
                    if tar_links:
                        tar_file = tar_links[0]
                        full_url = args.url.rstrip('/') + '/' + tar_file
                        print(f"Found tar file: {tar_file}")
                        print(f"Downloading {full_url}")
                        tar_path = workdir_path / tar_file
                        urllib.request.urlretrieve(full_url, str(tar_path), reporthook=download_progress)
                        print("\nDownload complete.")
                    else:
                        sys.exit(f"Error: No tar files found in directory listing at {args.url}")
            except Exception as e:
                sys.exit(f"Error: Could not fetch directory listing: {e}")
        else:
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
    
    copy_tree(template_src, template_dst)

    # Move extracted contents to the working directory
    for item in extracted_dir.iterdir():
        src_item = item
        dst_item = workdir_path / item.name
        
        # Skip if it's the ASC directory (already copied)
        if item.name == args.asc:
            continue
        
        # Move the item
        if dst_item.exists():
            if dst_item.is_dir():
                shutil.rmtree(str(dst_item))
            else:
                dst_item.unlink()
        
        shutil.move(str(src_item), str(dst_item))
    
    # Remove the now-empty extracted directory
    shutil.rmtree(str(extracted_dir))

    print(f'Final working directory created at: {workdir_path.resolve()}')
    print("Process completed successfully.")

if __name__ == "__main__":
    main()