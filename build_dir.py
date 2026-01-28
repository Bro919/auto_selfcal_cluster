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
    extracted = False
    
    if tar_files:
        # Use the first tar file found
        tar_path = workdir_path / tar_files[0].name
        print(f"Found tar file: {tar_files[0].name}")
        shutil.copy(str(tar_files[0]), str(tar_path))
        print("Copied to working directory.")
        
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
            extracted = True
        except tarfile.ReadError as e:
            sys.exit(f"Error: Failed to extract tar file: {e}")
    else:
        # No tar file found locally, try downloading
        tar_name = Path(args.url).name
        tar_path = workdir_path / tar_name
        
        # If URL ends with /, it's a directory - need to find tar file or .ms directory inside
        if args.url.endswith('/'):
            def find_ms_url(url, depth=0):
                """Recursively search for .ms directory in URL"""
                if depth > 5:  # Prevent infinite recursion
                    return None
                
                print(f"Fetching directory listing from {url}")
                try:
                    with urllib.request.urlopen(url) as response:
                        html = response.read().decode('utf-8')
                        # Extract tar file links from HTML
                        tar_links = re.findall(r'href=["\']([^"\']*\.tar[^"\']*)["\']', html)
                        # Extract .ms directory links
                        ms_links = re.findall(r'href=["\']([^"\']*\.ms/?)["\']', html)
                        # Extract all directory links (ending with /)
                        dir_links = re.findall(r'href=["\']([^"\']+/)["\']', html)
                        
                        if tar_links:
                            # Prefer tar file if available
                            tar_file = tar_links[0]
                            return ('tar', url.rstrip('/') + '/' + tar_file)
                        
                        if ms_links:
                            # Found .ms directory - return its full URL
                            ms_dir = ms_links[0].rstrip('/')
                            return ('ms', url.rstrip('/') + '/' + ms_dir)
                        
                        # No tar or .ms found at this level, try subdirectories
                        # Filter out parent dir (..) and current dir references
                        subdirs = [d for d in dir_links if not d.startswith('../') and d != './']
                        
                        if subdirs:
                            print(f"No tar or .ms found at this level, checking subdirectories...")
                            for subdir in subdirs:
                                subdir_url = url.rstrip('/') + '/' + subdir
                                result = find_ms_url(subdir_url, depth + 1)
                                if result:
                                    return result
                        
                        return None
                except Exception as e:
                    print(f"Warning: Could not fetch directory listing from {url}: {e}")
                    return None
            
            result = find_ms_url(args.url)
            if not result:
                sys.exit(f"Error: No tar or .ms directories found in {args.url} or subdirectories")
            
            file_type, full_url = result
            
            if file_type == 'tar':
                tar_path = workdir_path / Path(full_url).name
                print(f"Found tar file: {tar_path.name}")
                print(f"Downloading {full_url}")
                urllib.request.urlretrieve(full_url, str(tar_path), reporthook=download_progress)
                print("\nDownload complete.")
                
                # Verify and extract the tar file
                if not tarfile.is_tarfile(str(tar_path)):
                    sys.exit(f"Error: Downloaded file at {tar_path} is not a valid tar archive.")
                
                try:
                    with tarfile.open(str(tar_path), "r:*") as tar:
                        tar.extractall(path=workdir_path)
                    extracted = True
                except tarfile.ReadError as e:
                    sys.exit(f"Error: Failed to extract tar file: {e}")
            elif file_type == 'ms':
                # .ms directory found - will be handled in the search section below
                print(f"Found .ms directory, will search for it after checking local content")
                extracted = False
        else:
            print(f"Downloading {args.url}")
            urllib.request.urlretrieve(args.url, str(tar_path), reporthook=download_progress)
            print("\nDownload complete.")
            
            # Check if it's a tar file and extract if so
            if tarfile.is_tarfile(str(tar_path)):
                try:
                    with tarfile.open(str(tar_path), "r:*") as tar:
                        tar.extractall(path=workdir_path)
                    extracted = True
                except tarfile.ReadError as e:
                    sys.exit(f"Error: Failed to extract tar file: {e}")
            else:
                # Not a tar file, assume it's a directory structure
                extracted = False

    # Find .ms directory (either from extracted tar or downloaded directly)
    ms_dir = None
    
    if extracted or tar_path is None:
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
    else:
        # No tar file was extracted; look for .ms directory in workdir_path directly
        # This could happen if downloading a directory structure or if the download wasn't a tar
        ms_dirs = [p for p in workdir_path.rglob('*') if p.is_dir() and p.name.endswith('.ms')]
        
        if ms_dirs:
            if len(ms_dirs) > 1:
                print("Warning: Multiple .ms directories found; using the first one.")
            ms_dir = ms_dirs[0]
        else:
            # No .ms directory found, look for any directory in workdir_path
            all_dirs = [p for p in workdir_path.iterdir() if p.is_dir()]
            if all_dirs:
                if len(all_dirs) > 1:
                    print("Warning: No .ms directory found; using the first directory.")
                ms_dir = all_dirs[0]
            else:
                sys.exit(f"Error: No .ms directory or any directory found in {workdir_path}")

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

    # Copy ASC template contents directly into working directory
    template = Path(args.asc)
    # If the provided template is relative, interpret it relative to the current working directory.
    template_src = template if template.is_absolute() else (Path.cwd() / template)

    if not template_src.exists():
        sys.exit(f"Error: ACS directory {template_src} does not exist.")
    copy_tree(template_src, workdir_path)

    # Remove the now-empty top-level extracted directory if it still exists and is different from target
    try:
        if top_dir.exists() and top_dir.is_dir() and top_dir.resolve() != target_ms.resolve():
            shutil.rmtree(str(top_dir))
    except Exception as e:
        print(f"Warning: could not remove {top_dir}: {e}")

    print(f'Final working directory created at: {workdir_path.resolve()}')
    print("Process completed successfully.")

if __name__ == "__main__":
    main()