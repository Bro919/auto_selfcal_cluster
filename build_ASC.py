import argparse 
from pathlib import Path
import shutil
import tarfile
def extract_tar_with_progress(tar_path, extract_path):
    """Extract tar file with a progress bar."""
    with tarfile.open(str(tar_path), "r:*") as tar:
        members = tar.getmembers()
        total = len(members)
        if total == 0:
            print("No files to extract.")
            return
        print(f"Extracting {total} files from {tar_path}...")
        for i, member in enumerate(members, 1):
            tar.extract(member, path=extract_path)
            percent = min(i / total * 100, 100)
            print(f"\rExtracting: {percent:5.1f}% ({i}/{total})", end='', flush=True)
        print("\nExtraction complete.")
import sys
import urllib.request
from datetime import date
import re
import os

def download_progress(blocks, block_size, total_size):
    """Download progress bar"""
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

        # Skip version control metadata that may be unreadable or irrelevant
        if src_item.name == '.git' or src_item.name.startswith('.git'):
            print(f"Skipping VCS metadata directory: {src_item}")
            continue

        try:
            if src_item.is_dir():
                if dst_item.exists():
                    shutil.rmtree(str(dst_item))
                # Avoid copying .git contents and other common VCS/artifact files
                shutil.copytree(
                    str(src_item),
                    str(dst_item),
                    ignore=shutil.ignore_patterns('.git', '*.lock'),
                    ignore_dangling_symlinks=True
                )
            else:
                shutil.copy2(str(src_item), str(dst_item))
        except PermissionError as e:
            print(f"Warning: Permission error copying {src_item} -> {dst_item}: {e}")
        except shutil.Error as e:
            # shutil.copytree raises shutil.Error if some files couldn't be copied
            print(f"Warning: Error copying {src_item} -> {dst_item}: {e}")
        except Exception as e:
            print(f"Warning: Unexpected error copying {src_item} -> {dst_item}: {e}")

def main():
    parser = argparse.ArgumentParser(
        description="Download a tar file, extract it, and move a specified file to a new location, and create a working directory."
    )
    # Add argument definitions (required for parse_args to work)
    parser.add_argument("project_code", type=str, help="Project code (e.g., 23A-241)")
    parser.add_argument("object_name", type=str, help="Object name (e.g., AT2019ehz)")
    parser.add_argument("url", type=str, help="URL to download from")
    parser.add_argument("observation_date", type=str, help="Observation date (e.g., 2023-07-22)")
    parser.add_argument("--asc", type=str, default="ASC", help="ASC template directory (default: ASC)")
    parser.add_argument("--a_config", action="store_true", help="Set A_config True for special resources")
    args = parser.parse_args()
    obs_date = args.observation_date
    workdir_name = f"{args.project_code}.{args.object_name}.{obs_date}"
    workdir_path = Path(workdir_name)

    # Create working directory
    workdir_path.mkdir(parents=True, exist_ok=True)

    # Initialize extracted metadata variable
    extracted_project_code = None

    # --- Directory download approach first ---
    base_url = args.url.rstrip('/')

    def find_first_ms_dir(url, visited=None):
        """Recursively search for the first directory whose name ends with '.ms' and return
        a tuple (relative_path_from_start, ms_url). Returns None if not found."""
        if visited is None:
            visited = set()
        if url in visited:
            return None
        visited.add(url)

        try:
            print(f"Scanning for .ms directories at {url}")
            with urllib.request.urlopen(url) as response:
                html = response.read().decode('utf-8')
                links = re.findall(r'href=["\']([^"\'?]+)["\']', html)
                links = list(set(links))

                valid_links = []
                for link in links:
                    if link in ['../', './', '..', '.', '']:
                        continue
                    if link.startswith('/'):
                        continue
                    if '?C=' in link:
                        continue
                    valid_links.append(link)

                # Check for a .ms directory at this level
                for link in valid_links:
                    if link.endswith('/') and link.rstrip('/').endswith('.ms'):
                        ms_rel = link.rstrip('/')
                        ms_url = url.rstrip('/') + '/' + link.lstrip('/')
                        return (ms_rel, ms_url)

                # Recurse into subdirectories
                for link in valid_links:
                    if link.endswith('/'):
                        sub_url = url.rstrip('/') + '/' + link.lstrip('/')
                        res = find_first_ms_dir(sub_url, visited)
                        if res:
                            sub_rel, ms_url = res
                            combined_rel = link.rstrip('/') + '/' + sub_rel
                            return (combined_rel, ms_url)
        except Exception as e:
            print(f"Warning: Error scanning directory {url} for .ms: {e}")
        return None

    def get_all_files_from_directory(url, base_url=None, all_files=None, visited=None):
        """Recursively collect all file URLs from a directory listing and return tuples
        of (relative_path_from_base, full_file_url)."""
        if all_files is None:
            all_files = []
        if visited is None:
            visited = set()
        if base_url is None:
            base_url = url.rstrip('/')

        if url in visited:
            return all_files
        visited.add(url)

        try:
            print(f"Scanning directory: {url}")
            with urllib.request.urlopen(url) as response:
                html = response.read().decode('utf-8')
                links = re.findall(r'href=["\']([^"\'?]+)["\']', html)
                links = list(set(links))

                valid_links = []
                for link in links:
                    if link in ['../', './', '..', '.', '']:
                        continue
                    if link.startswith('/'):
                        continue
                    if '?C=' in link:
                        continue
                    valid_links.append(link)

                for link in valid_links:
                    item_url = url.rstrip('/') + '/' + link.lstrip('/')

                    if link.endswith('/'):
                        get_all_files_from_directory(item_url, base_url, all_files, visited)
                    else:
                        relative_path = item_url.replace(base_url.rstrip('/') + '/', '')
                        all_files.append((relative_path, item_url))

            return all_files
        except Exception as e:
            print(f"Warning: Error scanning directory {url}: {e}")
            return all_files

    # Try to find the first .ms directory and download only its contents when present
    # First, try the URL as-is (complete path scenario)
    ms_info = find_first_ms_dir(base_url)
    dir_url = base_url
    
    # If no results and project_code is not "unknown", try appending project_code (base URL scenario)
    if not ms_info and args.project_code != "unknown":
        dir_url = f"{base_url}/{args.project_code}"
        print(f"No .ms directory found at {base_url}; trying with project code: {dir_url}")
        ms_info = find_first_ms_dir(dir_url)
    
    if ms_info:
        ms_rel_path, ms_url = ms_info
        print(f"Found .ms directory: {ms_rel_path}; downloading only its contents from {ms_url}")
        all_files = get_all_files_from_directory(ms_url, base_url=ms_url)
        ms_found = True
    else:
        print("No .ms directory found in remote listing; downloading entire directory tree.")
        all_files = get_all_files_from_directory(dir_url, base_url=dir_url)
        ms_found = False

    if all_files:
        total_files = len(all_files)
        print(f"Found {total_files} files to download")
        temp_dir = workdir_path / "temp_download"
        for idx, (rel_path, file_url) in enumerate(all_files, 1):
            if ms_found:
                relative_path = Path(ms_rel_path) / Path(rel_path)
            else:
                relative_path = Path(rel_path)
            file_path = temp_dir / relative_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            print(f"Downloading: {relative_path}")
            try:
                # Show per-file progress for large files, else just download
                urllib.request.urlretrieve(file_url, str(file_path), reporthook=download_progress)
                print()  # Newline after per-file progress
            except Exception as e:
                print(f"Warning: Could not download {relative_path}: {e}")
            # Overall progress bar
            percent = min(idx / total_files * 100, 100)
            print(f"\rDirectory progress: {percent:5.1f}% ({idx}/{total_files} files)", end='', flush=True)
        print("\nDirectory download complete.")
        asc_name = Path(args.asc).name
        extracted_dirs = [p for p in temp_dir.iterdir() if p.is_dir() and p.name != asc_name]
        ms_dirs = []
        for d in extracted_dirs:
            if d.name.endswith('.ms'):
                ms_dirs.append(d)
            else:
                ms_dirs.extend([p for p in d.rglob('*') if p.is_dir() and p.name.endswith('.ms')])
        ms_dir = None
        target_ms = None
        extracted_project_code = None
        if ms_dirs:
            if len(ms_dirs) > 1:
                print("Warning: Multiple .ms directories found; using the first one.")
            ms_dir = ms_dirs[0]
            # Extract project code from the path before moving
            # e.g., temp_dir/24A-322/pipeline.../24A-322...ms -> extract "24A-322"
            path_parts = ms_dir.parts
            for part in path_parts:
                match = re.search(r'[0-9]{2}[A-Z]-[0-9]{3}', part)
                if match:
                    extracted_project_code = match.group(0)
                    break
            if extracted_project_code:
                print(f"Extracted project code from path: {extracted_project_code}")
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
        else:
            print("No .ms directory found in downloaded content. The remote URL may not contain a measurement set.")
            sys.exit("Error: No measurement set directory was found in the downloaded content. The remote URL may not contain an .ms or downloadable archive.")
        try:
            if temp_dir.exists():
                shutil.rmtree(str(temp_dir))
        except Exception as e:
            print(f"Warning: Could not remove temporary download directory: {e}")
    else:
        # --- Fallback to tar extraction if directory download fails ---
        print("No files found in directory download. Attempting tar extraction.")
        cwd = Path.cwd()
        tar_files = list(cwd.glob("*.tar*"))
        tar_path = None
        extracted_successfully = False
        if tar_files:
            tar_path = workdir_path / tar_files[0].name
            print(f"Found tar file: {tar_files[0].name}")
            shutil.copy(str(tar_files[0]), str(tar_path))
            print("Copied to working directory.")
            extracted_successfully = True
        else:
            tar_name = Path(args.url).name
            tar_path = workdir_path / tar_name
            if args.url.endswith('/'):
                print(f"Fetching directory listing from {args.url}")
                try:
                    with urllib.request.urlopen(args.url) as response:
                        html = response.read().decode('utf-8')
                        tar_links = re.findall(r'href=["\']([^"\']*.tar[^"\']*)["\']', html)
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
                            print(f"No tar files found in directory listing.")
                            tar_path = None
                except Exception as e:
                    sys.exit(f"Error: Could not fetch directory listing: {e}")
            else:
                print(f"Downloading {args.url}")
                urllib.request.urlretrieve(args.url, str(tar_path), reporthook=download_progress)
                print("\nDownload complete.")
                extracted_successfully = True
        if extracted_successfully and tar_path and tar_path.exists():
            if not tarfile.is_tarfile(str(tar_path)):
                sys.exit(f"Error: Downloaded file at {tar_path} is not a valid tar archive. The download may have been incomplete or corrupted.")
            try:
                extract_tar_with_progress(tar_path, workdir_path)
            except tarfile.ReadError as e:
                sys.exit(f"Error: Failed to extract tar file: {e}")
            asc_name = Path(args.asc).name
            extracted_dirs = [p for p in workdir_path.iterdir() if p.is_dir() and p.name != asc_name]
            if not extracted_dirs:
                sys.exit("Error: No extracted directories found.")
            if len(extracted_dirs) > 1:
                print("Warning: Multiple extracted directories found; searching all of them for .ms directories.")
            ms_dirs = []
            for extracted_dir in extracted_dirs:
                if extracted_dir.name.endswith('.ms'):
                    ms_dirs.append(extracted_dir)
                else:
                    ms_dirs.extend([p for p in extracted_dir.rglob('*') if p.is_dir() and p.name.endswith('.ms')])
            if not ms_dirs:
                sys.exit(f"Error: No directory with '.ms' suffix found inside extracted content at {workdir_path}.")
            if len(ms_dirs) > 1:
                print("Warning: Multiple .ms directories found; using the first one.")
            ms_dir = ms_dirs[0]
            # Extract project code from the path before moving
            path_parts = ms_dir.parts
            for part in path_parts:
                match = re.search(r'[0-9]{2}[A-Z]-[0-9]{3}', part)
                if match:
                    extracted_project_code = match.group(0)
                    break
            if extracted_project_code:
                print(f"Extracted project code from path: {extracted_project_code}")
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
            for extracted_dir in extracted_dirs:
                try:
                    if extracted_dir.exists() and extracted_dir.is_dir() and extracted_dir.resolve() != target_ms.resolve():
                        shutil.rmtree(str(extracted_dir))
                except Exception as e:
                    print(f"Warning: could not remove {extracted_dir}: {e}")
        else:
            print("No tar file found or extracted. Unable to proceed.")
            sys.exit("Error: No measurement set directory was found in the downloaded content. The remote URL may not contain an .ms or a downloadable tar archive.")
        # Clean up temp directory
        try:
            if 'temp_dir' in locals() and temp_dir.exists():
                shutil.rmtree(str(temp_dir))
        except Exception as e:
            print(f"Warning: Could not remove temporary download directory: {e}")


    # Copy ASC template contents directly into working directory
    template = Path(args.asc)
    template_src = template if template.is_absolute() else (Path.cwd() / template)
    if not template_src.exists():
        sys.exit(f"Error: ACS directory {template_src} does not exist.")
    copy_tree(template_src, workdir_path)

    print(f'Final working directory created at: {workdir_path.resolve()}')
    print("Process completed successfully.")

    # Write extracted metadata to a file for use by run_build_and_prep_ASC.py
    if extracted_project_code:
        metadata_file = workdir_path / ".extracted_metadata"
        try:
            with metadata_file.open("w") as f:
                f.write(f"project_code={extracted_project_code}\n")
            print(f"Wrote extracted metadata to {metadata_file}")
        except Exception as e:
            print(f"Warning: Could not write extracted metadata file: {e}")
    else:
        print("Warning: No project code was extracted from the path")

    # --- Edit prep and clean scripts in working directory ---
    prep_script = workdir_path / "prep-ms-for-auto-selfcal.py"
    clean_script = workdir_path / "clean_up_post_selfcal.py"

    ms_name = f"{workdir_name}.ms"
    root_dir = str(workdir_path.resolve())
    prefix_string = workdir_name

    if prep_script.exists():
        with prep_script.open("r", encoding="utf-8") as f:
            lines = f.readlines()
        a_config_found = False
        for i, line in enumerate(lines):
            if line.strip().startswith("measurement_set ="):
                lines[i] = f"measurement_set = \"{ms_name}\"\n"
            if line.strip().startswith("source_name ="):
                lines[i] = f"source_name = \"{args.object_name}\"\n"
            if line.strip().startswith("A_config ="):
                a_config_found = True
                if args.a_config:
                    lines[i] = 'A_config = True  # Set to True to use special resources for L band\n'
                else:
                    lines[i] = 'A_config = False  # Set to True to use special resources for L band\n'
        if not a_config_found:
            insert_idx = 0
            for idx, line in enumerate(lines):
                if line.startswith('import') or line.strip() == '':
                    insert_idx = idx + 1
            if args.a_config:
                lines.insert(insert_idx, 'A_config = True  # Set to True to use special resources for L band\n')
            else:
                lines.insert(insert_idx, 'A_config = False  # Set to True to use special resources for L band\n')
        with prep_script.open("w", encoding="utf-8") as f:
            f.writelines(lines)
        print(f"Updated {prep_script} with measurement_set, source_name, and A_config.")
    else:
        print(f"Warning: {prep_script} not found.")

    if clean_script.exists():
        with clean_script.open("r", encoding="utf-8") as f:
            lines = f.readlines()
        for i, line in enumerate(lines):
            if line.strip().startswith("root_dir ="):
                lines[i] = f"root_dir = \"{root_dir}\"\n"
            if line.strip().startswith("prefix_string ="):
                lines[i] = f"prefix_string = \"{prefix_string}\"\n"
        with clean_script.open("w", encoding="utf-8") as f:
            f.writelines(lines)
        print(f"Updated {clean_script} with root_dir and prefix_string.")
    else:
        print(f"Warning: {clean_script} not found.")

if __name__ == "__main__":
    main()