import argparse 
from pathlib import Path
import shutil
import tarfile
import sys
import urllib.request
from datetime import date
import re
import os

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
    # `asc` is usually a fixed template directory. Make it optional with a sensible default
    default_asc = Path(__file__).parent / "ASC"
    parser.add_argument("--asc", dest="asc", default=str(default_asc),
                        help=f"Path to the ACS directory (default: {default_asc})")

    args = parser.parse_args()

    today = date.today().isoformat()
    workdir_name = f"{args.project_code}.{args.object_name}.{today}"
    workdir_path = Path(workdir_name)

    # Create working directory
    workdir_path.mkdir(parents=True, exist_ok=True)

    # Check for existing tar files in current directory
    cwd = Path.cwd()
    tar_files = list(cwd.glob("*.tar*"))
    tar_path = None
    extracted_successfully = False
    
    if tar_files:
        # Use the first tar file found
        tar_path = workdir_path / tar_files[0].name
        print(f"Found tar file: {tar_files[0].name}")
        shutil.copy(str(tar_files[0]), str(tar_path))
        print("Copied to working directory.")
        extracted_successfully = True
    else:
        # Try to download the tar file
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
                        extracted_successfully = True
                    else:
                        print(f"No tar files found in directory listing. Attempting to download directory with project code name instead...")
                        tar_path = None  # Signal that we're using directory download instead
            except Exception as e:
                sys.exit(f"Error: Could not fetch directory listing: {e}")
        else:
            print(f"Downloading {args.url}")
            urllib.request.urlretrieve(args.url, str(tar_path), reporthook=download_progress)
            print("\nDownload complete.")
            extracted_successfully = True
    
    # If we have a tar file, process it normally
    if extracted_successfully and tar_path and tar_path.exists():
        # Verify the tar file exists and is valid
        if not tarfile.is_tarfile(str(tar_path)):
            sys.exit(f"Error: Downloaded file at {tar_path} is not a valid tar archive. The download may have been incomplete or corrupted.")
        
        # Extract the tar file
        try:
            with tarfile.open(str(tar_path), "r:*") as tar:
                tar.extractall(path=workdir_path)
        except tarfile.ReadError as e:
            sys.exit(f"Error: Failed to extract tar file: {e}")

        # Find extracted directory (top-level)
        # Compare directory names when excluding the ASC template from extracted dirs
        asc_name = Path(args.asc).name
        extracted_dirs = [p for p in workdir_path.iterdir() if p.is_dir() and p.name != asc_name]

        if not extracted_dirs:
            sys.exit("Error: No extracted directories found.")
        if len(extracted_dirs) > 1:
            print("Warning: Multiple extracted directories found; using the first one.")
        top_dir = extracted_dirs[0]

        # Search for a directory with '.ms' suffix inside the extracted tree (including top_dir itself)
        ms_dirs = []
        if top_dir.name.endswith('.ms'):
            ms_dirs.append(top_dir)
        else:
            ms_dirs = [p for p in top_dir.rglob('*') if p.is_dir() and p.name.endswith('.ms')]

        ms_dir = None
        if not ms_dirs:
            # Fallback: if top_dir contains exactly one subdirectory, use it
            inner_dirs = [p for p in top_dir.iterdir() if p.is_dir()]
            if len(inner_dirs) == 1:
                ms_dir = inner_dirs[0]
                print(f"No .ms dir found; using inner directory {ms_dir.name}")
            else:
                sys.exit(f"Error: No directory with '.ms' suffix found inside {top_dir}")
        else:
            if len(ms_dirs) > 1:
                print("Warning: Multiple .ms directories found; using the first one.")
            ms_dir = ms_dirs[0]

        # Move the found .ms directory into the working directory and rename it
        target_ms = workdir_path / f"{workdir_name}.ms"
        if target_ms.exists():
            if target_ms.is_dir():
                shutil.rmtree(str(target_ms))
            else:
                target_ms.unlink()

        try:
            shutil.move(str(ms_dir), str(target_ms))
        except Exception as e:
            sys.exit(f"Error: Failed to move .ms directory {ms_dir} to {target_ms}: {e}")

        # Remove the now-empty top-level extracted directory if it still exists and is different from target
        try:
            if top_dir.exists() and top_dir.is_dir() and top_dir.resolve() != target_ms.resolve():
                shutil.rmtree(str(top_dir))
        except Exception as e:
            print(f"Warning: could not remove {top_dir}: {e}")
    
    else:
        # No tar file found - attempt to download directory with project code name
        print(f"Attempting to download directory with project code name: {args.project_code}")
        base_url = args.url.rstrip('/')
        dir_url = f"{base_url}/{args.project_code}"
        
        try:
            print(f"Fetching directory listing from {dir_url}")
            with urllib.request.urlopen(dir_url) as response:
                html = response.read().decode('utf-8')
                # Extract file links from HTML
                file_links = re.findall(r'href=["\']([^"\']+)["\']', html)
                
                if not file_links:
                    sys.exit(f"Error: Could not find any files in directory {dir_url}")
                
                # Filter out parent directory links and query parameters
                file_links = [f for f in file_links if f != '../' and f != '.' and not f.endswith('?')]
                
                if not file_links:
                    sys.exit(f"Error: No valid files found in directory {dir_url}")
                
                print(f"Found {len(file_links)} files in remote directory")
                
                # Download all files from the remote directory
                for file_name in file_links:
                    file_url = f"{dir_url}/{file_name}"
                    file_path = workdir_path / file_name
                    
                    print(f"Downloading {file_name}...", end=' ')
                    try:
                        urllib.request.urlretrieve(file_url, str(file_path))
                        print("done")
                    except Exception as e:
                        print(f"Warning: Could not download {file_name}: {e}")
                
                print("Directory download complete.")
                
                # Create a .ms directory if it doesn't exist
                target_ms = workdir_path / f"{workdir_name}.ms"
                if not target_ms.exists():
                    target_ms.mkdir(parents=True, exist_ok=True)
                    print(f"Created .ms directory: {target_ms.name}")
        
        except Exception as e:
            sys.exit(f"Error: Could not download directory from {dir_url}: {e}")

    # Copy ASC template contents directly into working directory
    template = Path(args.asc)
    # If the provided template is relative, interpret it relative to the current working directory.
    template_src = template if template.is_absolute() else (Path.cwd() / template)

    if not template_src.exists():
        sys.exit(f"Error: ACS directory {template_src} does not exist.")
    copy_tree(template_src, workdir_path)

    print(f'Final working directory created at: {workdir_path.resolve()}')
    print("Process completed successfully.")

if __name__ == "__main__":
    main()