import argparse
import logging
import re
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple


def configure_logging(verbose: bool, quiet: bool = False) -> logging.Logger:
    if quiet and not verbose:
        level = logging.WARNING
    else:
        level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="[%(levelname)s] %(message)s")
    return logging.getLogger("build_CB")


def download_progress(blocks: int, block_size: int, total_size: int) -> None:
    if total_size <= 0:
        return

    downloaded = blocks * block_size
    percent = min(downloaded / total_size * 100, 100)
    mb_done = downloaded / (1024 * 1024)
    mb_total = total_size / (1024 * 1024)

    print(
        f"\rDownloading: {percent:5.1f}% ({mb_done:6.1f} MB / {mb_total:.1f} MB)",
        end="",
        flush=True,
    )


def extract_tar_with_progress(tar_path: Path, extract_path: Path) -> None:
    with tarfile.open(str(tar_path), "r:*") as tar:
        members = tar.getmembers()
        total = len(members)
        if total == 0:
            print("No files to extract.")
            return

        print(f"Extracting {total} files from {tar_path}...")
        for index, member in enumerate(members, 1):
            tar.extract(member, path=extract_path)
            percent = min(index / total * 100, 100)
            print(f"\rExtracting: {percent:5.1f}% ({index}/{total})", end="", flush=True)
        print("\nExtraction complete.")


def copy_tree(src: Path, dst: Path) -> None:
    src = Path(src)
    dst = Path(dst)

    if src.resolve() == dst.resolve():
        print(f"Skipping copy because source and destination are the same: {src}")
        return

    dst.mkdir(parents=True, exist_ok=True)
    ignore_names = shutil.ignore_patterns(".git", ".hg", ".svn", "*.lock")

    for item in src.iterdir():
        if item.name in {".git", ".hg", ".svn"}:
            continue

        src_item = src / item.name
        dst_item = dst / item.name
        if src_item.resolve() == dst_item.resolve():
            continue

        try:
            if src_item.is_dir():
                if dst_item.exists():
                    shutil.rmtree(str(dst_item))
                shutil.copytree(
                    str(src_item),
                    str(dst_item),
                    ignore=ignore_names,
                    ignore_dangling_symlinks=True,
                )
            else:
                shutil.copy2(str(src_item), str(dst_item))
        except PermissionError as exc:
            print(f"Warning: Permission error copying {src_item} -> {dst_item}: {exc}")
        except shutil.Error as exc:
            print(f"Warning: Error copying {src_item} -> {dst_item}: {exc}")
        except Exception as exc:
            print(f"Warning: Unexpected error copying {src_item} -> {dst_item}: {exc}")


def is_tar_url(url: str) -> bool:
    lower = url.lower()
    return any(lower.endswith(ext) for ext in (".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz"))


def safe_remove(path: Path) -> None:
    path = Path(path)
    try:
        if path.exists() and path.is_file():
            path.unlink()
    except Exception as exc:
        print(f"Warning: Could not remove temporary file {path}: {exc}")


def parse_directory_links(html: str) -> List[str]:
    links = re.findall(r'href=["\']([^"\'?]+)["\']', html)
    unique_links = sorted(set(links))

    valid_links = []
    for link in unique_links:
        if link in {"../", "./", "..", ".", ""}:
            continue
        if link.startswith("/"):
            continue
        if "?C=" in link:
            continue
        valid_links.append(link)

    return valid_links


def fetch_directory_links(url: str, logger: Optional[logging.Logger] = None) -> List[str]:
    if logger:
        logger.debug("Scanning directory listing: %s", url)
    with urllib.request.urlopen(url) as response:
        html = response.read().decode("utf-8", errors="ignore")
    return parse_directory_links(html)


def find_first_observation_dir(
    url: str,
    visited: Optional[Set[str]] = None,
    logger: Optional[logging.Logger] = None,
) -> Optional[Tuple[str, str]]:
    if visited is None:
        visited = set()
    if url in visited:
        return None
    visited.add(url)

    try:
        valid_links = fetch_directory_links(url, logger=logger)

        for link in valid_links:
            if link.endswith("/") and link.rstrip("/").startswith("observation"):
                obs_rel = link.rstrip("/")
                obs_url = url.rstrip("/") + "/" + link.lstrip("/")
                return obs_rel, obs_url

        for link in valid_links:
            if not link.endswith("/"):
                continue
            sub_url = url.rstrip("/") + "/" + link.lstrip("/")
            result = find_first_observation_dir(sub_url, visited, logger=logger)
            if result:
                sub_rel, obs_url = result
                return link.rstrip("/") + "/" + sub_rel, obs_url
    except Exception as exc:
        print(f"Warning: Error scanning directory {url} for observation subdirectories: {exc}")

    return None


def get_all_files_from_directory(
    url: str,
    base_url: Optional[str] = None,
    all_files: Optional[List[Tuple[str, str]]] = None,
    visited: Optional[Set[str]] = None,
    logger: Optional[logging.Logger] = None,
) -> List[Tuple[str, str]]:
    if all_files is None:
        all_files = []
    if visited is None:
        visited = set()
    if base_url is None:
        base_url = url.rstrip("/")

    if url in visited:
        return all_files
    visited.add(url)

    try:
        valid_links = fetch_directory_links(url, logger=logger)

        for link in valid_links:
            item_url = url.rstrip("/") + "/" + link.lstrip("/")
            if link.endswith("/"):
                get_all_files_from_directory(item_url, base_url, all_files, visited, logger=logger)
            else:
                relative_path = item_url.replace(base_url.rstrip("/") + "/", "")
                all_files.append((relative_path, item_url))
    except Exception as exc:
        print(f"Warning: Error scanning directory {url}: {exc}")

    return all_files


def find_observation_subdir_in_path(root_path: Path) -> Optional[Path]:
    root_path = Path(root_path)

    if root_path.name.startswith("observation") and root_path.is_dir():
        return root_path

    for child in sorted(root_path.iterdir()):
        if child.is_dir() and child.name.startswith("observation"):
            return child

    for child in sorted(root_path.iterdir()):
        if not child.is_dir():
            continue
        nested = find_observation_subdir_in_path(child)
        if nested:
            return nested

    return None


def download_directory(
    directory_url: str,
    target_dir: Path,
    logger: Optional[logging.Logger] = None,
    quiet: bool = False,
) -> None:
    file_list = get_all_files_from_directory(directory_url, base_url=directory_url, logger=logger)
    if not file_list:
        raise RuntimeError(f"No files found for directory download at {directory_url}")

    total = len(file_list)
    print(f"Found {total} files to download")
    completed = 0
    for idx, (relative_path, file_url) in enumerate(file_list, start=1):
        destination = target_dir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)

        if idx > 1 and not quiet:
            print()
        if not quiet:
            print(f"Downloading: {relative_path}")
        urllib.request.urlretrieve(file_url, str(destination), reporthook=download_progress)
        if not quiet:
            print()

        completed += 1
        percent = min(idx / total * 100, 100)
        if quiet:
            if idx == total or idx % 10 == 0:
                print(f"Directory progress: {percent:5.1f}% ({idx}/{total} files)")
        else:
            print(f"\rDirectory progress: {percent:5.1f}% ({idx}/{total} files)", end="", flush=True)

    if quiet:
        print(f"Directory download complete ({completed}/{total} files).")
    else:
        print("\nDirectory download complete.")


def update_casa_import_block(script_path: Path, observation_dir_name: str) -> None:
    if not script_path.exists():
        print(f"Warning: {script_path} not found, cannot update hifv_importdata call.")
        return

    text = script_path.read_text(encoding="utf-8")
    pattern = re.compile(r"hifv_importdata\s*\(\s*vis\s*=\s*\[\s*['\"]([^'\"]+)['\"]\s*\]\s*\)")

    if observation_dir_name == ".":
        replacement = "hifv_importdata(vis=['.'])"
    else:
        replacement = f"hifv_importdata(vis=['{observation_dir_name}'])"

    new_text, count = pattern.subn(replacement, text, count=1)
    if count == 0:
        print(f"Warning: Could not find a hifv_importdata(vis=[...]) call to patch in {script_path}.")
        return

    script_path.write_text(new_text, encoding="utf-8")
    print(f"Updated {script_path} to import {observation_dir_name}.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a CB working directory from a remote or local observation dataset."
    )
    parser.add_argument("project_code", nargs="?", help="Project code, e.g. 23A-241")
    parser.add_argument("object_name", nargs="?", help="Object name, e.g. AT2019ehz")
    parser.add_argument("observation_date", nargs="?", help="Observation date, e.g. 2023-07-22")
    parser.add_argument(
        "url_arg",
        nargs="?",
        help="Optional URL/path argument, either raw value or url=<value> after positional args",
    )
    parser.add_argument("--url", help="URL or local path to tar file/directory")
    parser.add_argument("--cb", type=str, default="CB", help="Path to the CB template directory")
    parser.add_argument("--temp-dir", type=str, default=None, help="Directory for temporary downloads/extraction")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose debug logging")
    parser.add_argument("-q", "--quiet", action="store_true", help="Reduce non-critical output noise")
    return parser.parse_args()


def parse_named_inputs(inputs: Sequence[str]) -> Tuple[Dict[str, str], List[str]]:
    named_inputs: Dict[str, str] = {}
    positional_inputs: List[str] = []
    for token in inputs:
        if "=" in token and not token.startswith("--"):
            key, value = token.split("=", 1)
            named_inputs[key.strip()] = value.strip()
        else:
            positional_inputs.append(token)
    return named_inputs, positional_inputs


def _looks_like_date(value: Optional[str]) -> bool:
    if not value:
        return False
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}$", value))


def normalize_cli_inputs(args: argparse.Namespace) -> argparse.Namespace:
    named_inputs, _ = parse_named_inputs(sys.argv[1:])

    if named_inputs.get("project_code") and not args.project_code:
        args.project_code = named_inputs["project_code"]
    if named_inputs.get("object_name") and not args.object_name:
        args.object_name = named_inputs["object_name"]
    if named_inputs.get("observation_date") and not args.observation_date:
        args.observation_date = named_inputs["observation_date"]
    if named_inputs.get("url") and not args.url:
        args.url = named_inputs["url"]

    for attr in ("project_code", "object_name", "observation_date"):
        value = getattr(args, attr)
        if value and isinstance(value, str) and value.startswith("url="):
            extracted_url = value.split("=", 1)[1].strip()
            if extracted_url and not args.url:
                args.url = extracted_url
            setattr(args, attr, None)

    # Handle split form: "url= /path/or/url".
    if args.url in (None, ""):
        saw_url_marker = False
        for attr in ("project_code", "object_name", "observation_date", "url_arg"):
            value = getattr(args, attr, None)
            if not value or not isinstance(value, str):
                continue
            if value.lower() == "url=":
                saw_url_marker = True
                setattr(args, attr, None)
                continue
            if saw_url_marker:
                args.url = value
                setattr(args, attr, None)
                break

    # Backward compatibility: old order was project object url observation_date.
    if args.url in (None, "") and args.observation_date and args.url_arg:
        if not _looks_like_date(args.observation_date) and _looks_like_date(args.url_arg):
            args.url = args.observation_date
            args.observation_date = args.url_arg
            args.url_arg = None

    if not args.url and args.url_arg:
        if str(args.url_arg).startswith("url="):
            args.url = str(args.url_arg).split("=", 1)[1]
        else:
            args.url = args.url_arg

    return args


def resolve_observation_dir_from_local_input(input_path: Path, temp_dir: Path) -> Path:
    if input_path.is_dir():
        found = find_observation_subdir_in_path(input_path)
        if found:
            return found
        if input_path.name.startswith("observation"):
            return input_path
        raise RuntimeError(f"No subdirectory starting with 'observation' found inside {input_path}.")

    if input_path.is_file():
        if not tarfile.is_tarfile(str(input_path)):
            raise RuntimeError(f"Local file {input_path} is not a valid tar archive.")

        tar_copy = temp_dir / input_path.name
        shutil.copy(str(input_path), str(tar_copy))
        extract_tar_with_progress(tar_copy, temp_dir)
        safe_remove(tar_copy)

        found = find_observation_subdir_in_path(temp_dir)
        if not found:
            raise RuntimeError("No observation* directory found inside extracted tar archive.")
        return found

    raise RuntimeError(f"Input path is neither a file nor a directory: {input_path}")


def resolve_observation_dir_from_remote(url: str, temp_dir: Path, logger: logging.Logger, quiet: bool = False) -> Path:
    if is_tar_url(url):
        tar_name = Path(url).name or "remote.tar"
        tar_path = temp_dir / tar_name
        print(f"Downloading tar file from {url}")
        urllib.request.urlretrieve(url, str(tar_path), reporthook=download_progress)
        print("\nDownload complete.")

        if not tarfile.is_tarfile(str(tar_path)):
            raise RuntimeError(f"Downloaded file is not a valid tar archive: {tar_path}")

        extract_tar_with_progress(tar_path, temp_dir)
        safe_remove(tar_path)

        found = find_observation_subdir_in_path(temp_dir)
        if not found:
            raise RuntimeError("No observation* directory found inside extracted tar archive.")
        return found

    logger.info("Scanning remote directory for observation* subdirectory at %s", url)
    obs_info = find_first_observation_dir(url, logger=logger)
    if obs_info:
        obs_rel, obs_url = obs_info
        observation_dir_name = Path(obs_rel).name
        logger.info("Found observation directory: %s", observation_dir_name)
        downloaded_root = temp_dir / observation_dir_name
        downloaded_root.mkdir(parents=True, exist_ok=True)
        download_directory(obs_url, downloaded_root, logger=logger, quiet=quiet)
        return downloaded_root

    raise RuntimeError(
        "No observation* directory discovered in remote listing and no tar URL provided. "
        "Provide a direct tar URL, a local path, or a listing containing observation* subdirectories."
    )


def stage_observation_contents(downloaded_dir: Path, workdir_path: Path) -> str:
    print(f"Moving contents of downloaded observation directory {downloaded_dir} into {workdir_path}")
    moved_names: List[str] = []

    for item in downloaded_dir.iterdir():
        destination = workdir_path / item.name
        if destination.exists():
            if destination.is_dir():
                shutil.rmtree(str(destination))
            else:
                destination.unlink()
        shutil.move(str(item), str(destination))
        moved_names.append(item.name)

    if len(moved_names) == 1 and (workdir_path / moved_names[0]).is_dir():
        return moved_names[0]
    return "."


def main() -> None:
    args = normalize_cli_inputs(parse_args())
    logger = configure_logging(args.verbose, args.quiet)

    missing = []
    if not args.project_code:
        missing.append("project_code")
    if not args.object_name:
        missing.append("object_name")
    if not args.observation_date:
        missing.append("observation_date")
    if not args.url:
        missing.append("url")
    if missing:
        sys.exit(
            "Usage error: missing required values: "
            + ", ".join(missing)
            + ". Provide project_code object_name observation_date URL/PATH, or use named inputs (e.g., url=...)."
        )

    workdir_name = f"working.{args.project_code}.{args.object_name}.{args.observation_date}"
    workdir_path = Path(workdir_name)
    if workdir_path.exists():
        sys.exit(f"Error: Working directory {workdir_path} already exists.")

    workdir_path.mkdir(parents=True, exist_ok=False)
    print(f"Created working directory: {workdir_path}")

    script_dir = Path(__file__).resolve().parent
    cb_template = Path(args.cb)
    cb_template_src = cb_template if cb_template.is_absolute() else (script_dir / cb_template)

    temp_root = Path(args.temp_dir).expanduser().resolve() if args.temp_dir else Path.cwd()
    temp_root.mkdir(parents=True, exist_ok=True)
    print(f"Using temporary directory root: {temp_root}")

    observation_subdir_name = None

    with tempfile.TemporaryDirectory(dir=str(temp_root), prefix="build_cb_") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        input_path = Path(args.url).expanduser()

        try:
            if input_path.exists():
                logger.info("Using local input path: %s", input_path)
                downloaded_dir = resolve_observation_dir_from_local_input(input_path, temp_dir)
            else:
                logger.info("Using remote input URL: %s", args.url)
                downloaded_dir = resolve_observation_dir_from_remote(args.url, temp_dir, logger, quiet=args.quiet)
        except Exception as exc:
            sys.exit(f"Error: {exc}")

        observation_subdir_name = stage_observation_contents(downloaded_dir, workdir_path)

    if not cb_template_src.exists():
        sys.exit(f"Error: CB template directory {cb_template_src} does not exist.")

    print(f"Copying CB template contents from {cb_template_src} into {workdir_path}")
    copy_tree(cb_template_src, workdir_path)

    casa_script = workdir_path / "casa_pipescript_666.py"
    update_casa_import_block(casa_script, observation_subdir_name)

    print(f"Final working directory created at: {workdir_path.resolve()}")
    print("Process completed successfully.")


if __name__ == "__main__":
    main()
