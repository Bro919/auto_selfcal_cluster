import argparse
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile
import urllib.request
import urllib.error
import re


def download_progress(blocks, block_size, total_size):
    if total_size <= 0:
        return
    downloaded = blocks * block_size
    percent = min(downloaded / total_size * 100, 100)
    mb_done = downloaded / (1024 * 1024)
    mb_total = total_size / (1024 * 1024)
    print(
        f"\rDownloading: {percent:5.1f}% ({mb_done:6.1f} MB / {mb_total:.1f} MB)",
        end=' ',
        flush=True,
    )


def extract_tar_with_progress(tar_path, extract_path):
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


def copy_tree(src, dst):
    src = Path(src)
    dst = Path(dst)

    if src.resolve() == dst.resolve():
        print(f"Skipping copy because source and destination are the same: {src}")
        return

    if not dst.exists():
        dst.mkdir(parents=True, exist_ok=True)

    for item in src.iterdir():
        src_item = src / item.name
        dst_item = dst / item.name

        if src_item.resolve() == dst_item.resolve():
            continue

        if src_item.name == '.git' or src_item.name.startswith('.git'):
            continue

        try:
            if src_item.is_dir():
                if dst_item.exists():
                    shutil.rmtree(str(dst_item))
                shutil.copytree(
                    str(src_item),
                    str(dst_item),
                    ignore=shutil.ignore_patterns('.git', '*.lock'),
                    ignore_dangling_symlinks=True,
                )
            else:
                shutil.copy2(str(src_item), str(dst_item))
        except PermissionError as e:
            print(f"Warning: Permission error copying {src_item} -> {dst_item}: {e}")
        except shutil.Error as e:
            print(f"Warning: Error copying {src_item} -> {dst_item}: {e}")
        except Exception as e:
            print(f"Warning: Unexpected error copying {src_item} -> {dst_item}: {e}")


def is_tar_url(url):
    lower = url.lower()
    return any(lower.endswith(ext) for ext in ['.tar', '.tar.gz', '.tgz', '.tar.bz2', '.tar.xz'])


def safe_remove(path):
    path = Path(path)
    try:
        if path.exists():
            path.unlink()
    except Exception as e:
        print(f"Warning: Could not remove temporary file {path}: {e}")


def find_first_observations_dir(url, visited=None):
    if visited is None:
        visited = set()
    if url in visited:
        return None
    visited.add(url)

    try:
        with urllib.request.urlopen(url) as response:
            html = response.read().decode('utf-8', errors='ignore')
            links = re.findall(r'href=["\']([^"\'?]+)["\']', html)
            links = list(dict.fromkeys(links))

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
                if link.endswith('/') and link.rstrip('/').startswith('observations'):
                    obs_rel = link.rstrip('/')
                    obs_url = url.rstrip('/') + '/' + link.lstrip('/')
                    return (obs_rel, obs_url)

            for link in valid_links:
                if link.endswith('/'):
                    sub_url = url.rstrip('/') + '/' + link.lstrip('/')
                    result = find_first_observations_dir(sub_url, visited)
                    if result:
                        sub_rel, obs_url = result
                        combined_rel = link.rstrip('/') + '/' + sub_rel
                        return (combined_rel, obs_url)
    except Exception as e:
        print(f"Warning: Error scanning directory {url} for observations subdirectories: {e}")
    return None


def get_all_files_from_directory(url, base_url=None, all_files=None, visited=None):
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
        with urllib.request.urlopen(url) as response:
            html = response.read().decode('utf-8', errors='ignore')
            links = re.findall(r'href=["\']([^"\'?]+)["\']', html)
            links = list(dict.fromkeys(links))

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


def find_observations_subdir_in_path(root_path):
    if root_path.name.startswith('observations') and root_path.is_dir():
        return root_path
    for child in sorted(root_path.iterdir()):
        if child.is_dir() and child.name.startswith('observations'):
            return child
    for child in sorted(root_path.iterdir()):
        if child.is_dir():
            result = find_observations_subdir_in_path(child)
            if result:
                return result
    return None


def download_directory(directory_url, target_dir):
    file_list = get_all_files_from_directory(directory_url, base_url=directory_url)
    if not file_list:
        raise RuntimeError(f"No files found for directory download at {directory_url}")
    for idx, (relative_path, file_url) in enumerate(file_list, start=1):
        destination = target_dir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        print(f"Downloading: {relative_path}")
        urllib.request.urlretrieve(file_url, str(destination), reporthook=download_progress)
        print()
        percent = min(idx / len(file_list) * 100, 100)
        print(f"\rDirectory progress: {percent:5.1f}% ({idx}/{len(file_list)} files)", end='', flush=True)
    print("\nDirectory download complete.")


def update_casa_import_block(script_path, observations_dir_name):
    if not script_path.exists():
        print(f"Warning: {script_path} not found, cannot update hifv_importdata call.")
        return

    text = script_path.read_text(encoding='utf-8')
    pattern = re.compile(
        r"hifv_importdata\s*\(\s*vis\s*=\s*\[\s*['\"]([^'\"]+)['\"]\s*\]\s*\)",
    )
    replacement = f"hifv_importdata(vis=['{observations_dir_name}'])"
    new_text, count = pattern.subn(replacement, text, count=1)
    if count == 0:
        print(f"Warning: Could not find a hifv_importdata(vis=[...]) call to patch in {script_path}.")
        return
    script_path.write_text(new_text, encoding='utf-8')
    print(f"Updated {script_path} to import {observations_dir_name}.")


def main():
    parser = argparse.ArgumentParser(
        description='Create a CB working directory from a remote or local observations dataset.'
    )
    parser.add_argument('project_code', type=str, help='Project code, e.g. 23A-241')
    parser.add_argument('object_name', type=str, help='Object name, e.g. AT2019ehz')
    parser.add_argument('url', type=str, help='URL or local path to the tar file or directory')
    parser.add_argument('observation_date', type=str, help='Observation date, e.g. 2023-07-22')
    parser.add_argument('--cb', type=str, default='CB', help='Path to the CB template directory')
    args = parser.parse_args()

    workdir_name = f"working.{args.project_code}.{args.object_name}.{args.observation_date}"
    workdir_path = Path(workdir_name)
    if workdir_path.exists():
        sys.exit(f"Error: Working directory {workdir_path} already exists.")

    workdir_path.mkdir(parents=True, exist_ok=False)
    print(f"Created working directory: {workdir_path}")

    script_dir = Path(__file__).resolve().parent
    cb_template = Path(args.cb)
    cb_template_src = cb_template if cb_template.is_absolute() else script_dir / cb_template

    downloaded_dir = None
    observations_subdir_name = None

    with tempfile.TemporaryDirectory() as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        input_path = Path(args.url)

        if input_path.exists():
            if input_path.is_dir():
                found = find_observations_subdir_in_path(input_path)
                if found:
                    downloaded_dir = found
                elif input_path.name.startswith('observations'):
                    downloaded_dir = input_path
                else:
                    sys.exit(f"Error: No subdirectory starting with 'observations' found inside local directory {input_path}.")
            elif input_path.is_file():
                if tarfile.is_tarfile(str(input_path)):
                    tar_copy = temp_dir / input_path.name
                    shutil.copy(str(input_path), str(tar_copy))
                    extract_tar_with_progress(tar_copy, temp_dir)
                    safe_remove(tar_copy)
                    found = find_observations_subdir_in_path(temp_dir)
                    if not found:
                        sys.exit("Error: No observations* directory found inside extracted tar archive.")
                    downloaded_dir = found
                else:
                    sys.exit(f"Error: Local file {input_path} is not a valid tar archive.")
        else:
            if is_tar_url(args.url):
                tar_name = Path(args.url).name
                tar_path = temp_dir / tar_name
                print(f"Downloading tar file from {args.url}")
                urllib.request.urlretrieve(args.url, str(tar_path), reporthook=download_progress)
                print("\nDownload complete.")
                extract_tar_with_progress(tar_path, temp_dir)
                safe_remove(tar_path)
                found = find_observations_subdir_in_path(temp_dir)
                if not found:
                    sys.exit("Error: No observations* directory found inside extracted tar archive.")
                downloaded_dir = found
            else:
                print(f"Scanning remote directory for observations* subdirectory at {args.url}")
                obs_info = find_first_observations_dir(args.url)
                if obs_info:
                    obs_rel, obs_url = obs_info
                    observations_subdir_name = Path(obs_rel).name
                    print(f"Found observations dir: {observations_subdir_name}")
                    downloaded_root = temp_dir / observations_subdir_name
                    downloaded_root.mkdir(parents=True, exist_ok=True)
                    download_directory(obs_url, downloaded_root)
                    downloaded_dir = downloaded_root
                else:
                    print("No direct observations* directory found in remote listing. Downloading entire directory tree and searching after extraction.")
                    archive_path = temp_dir / 'remote_dir.tar'
                    try:
                        urllib.request.urlretrieve(args.url, str(archive_path), reporthook=download_progress)
                        print("\nDownloaded remote URL to temporary archive, trying to extract.")
                        if tarfile.is_tarfile(str(archive_path)):
                            extract_tar_with_progress(archive_path, temp_dir)
                            safe_remove(archive_path)
                            found = find_observations_subdir_in_path(temp_dir)
                            if found:
                                downloaded_dir = found
                            else:
                                sys.exit("Error: No observations* subdirectory found in extracted temporary archive.")
                        else:
                            safe_remove(archive_path)
                            sys.exit("Error: The URL did not return a tar archive and no observations* directory could be discovered.")
                    except Exception as e:
                        safe_remove(archive_path)
                        sys.exit(f"Error: Failed to download or inspect remote URL: {e}")

        if downloaded_dir is None:
            sys.exit("Error: Failed to obtain an observations* directory from the provided URL or local path.")

        if observations_subdir_name is None:
            observations_subdir_name = downloaded_dir.name

        target_downloaded_dir = workdir_path / observations_subdir_name
        if target_downloaded_dir.exists():
            if target_downloaded_dir.is_dir():
                shutil.rmtree(str(target_downloaded_dir))
            else:
                target_downloaded_dir.unlink()

        print(f"Moving downloaded observations directory {downloaded_dir} to {target_downloaded_dir}")
        shutil.move(str(downloaded_dir), str(target_downloaded_dir))

    if not cb_template_src.exists():
        sys.exit(f"Error: CB template directory {cb_template_src} does not exist.")
    print(f"Copying CB template contents from {cb_template_src} into {workdir_path}")
    copy_tree(cb_template_src, workdir_path)

    casa_script = workdir_path / 'casa_pipescript_666.py'
    update_casa_import_block(casa_script, observations_subdir_name)

    print(f"Final working directory created at: {workdir_path.resolve()}")
    print("Process completed successfully.")


if __name__ == '__main__':
    main()
