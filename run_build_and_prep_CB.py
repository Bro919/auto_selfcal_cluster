#!/usr/bin/env python3

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Tuple
from urllib.parse import urlparse
import urllib.request

from build_CB import find_first_observation_dir, get_all_files_from_directory


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Build the CB workdir, generate the SLURM batch script, "
            "and optionally submit the job via sbatch."
        )
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        help=(
            "Optional positional values. Provide four values as "
            "project_code object_name url observation_date, or provide a single "
            "source path/URL to let metadata-scraper-CB.py infer the metadata."
        ),
    )
    parser.add_argument(
        "--source",
        help="Optional local path or URL to use when the metadata should be inferred automatically.",
    )
    parser.add_argument(
        "--cb",
        default="CB",
        help="Path to the CB template directory (default: CB)",
    )
    parser.add_argument(
        "--temp-dir",
        help="Optional temporary directory for downloads and extraction",
    )
    parser.add_argument(
        "--skip-submit",
        action="store_true",
        help="Build and prepare the job, but do not submit it.",
    )
    parser.add_argument(
        "--submit-dry-run",
        action="store_true",
        help="Print sbatch commands instead of executing them when submitting.",
    )
    parser.add_argument(
        "--submit-sleep-seconds",
        type=int,
        default=None,
        help="Seconds to wait between sbatch submissions.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the build/prep/submit commands without executing them.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging for build_CB.py during the build step.",
    )
    return parser.parse_args()


def compute_workdir(project_code: str, object_name: str, observation_date: str) -> Path:
    return Path(f"working.{project_code}.{object_name}.{observation_date}")


def parse_named_inputs(inputs):
    named_inputs = {}
    positional_inputs = []
    for token in inputs:
        if "=" in token and not token.startswith("--"):
            key, value = token.split("=", 1)
            named_inputs[key.strip()] = value.strip()
        else:
            positional_inputs.append(token)
    return named_inputs, positional_inputs


def collect_resolved_inputs(args: argparse.Namespace, named_inputs=None, positional_inputs=None) -> Tuple[str, str, str, str]:
    if named_inputs is None:
        named_inputs, positional_inputs = parse_named_inputs(args.inputs)

    project_code = named_inputs.get("project_code") or named_inputs.get("projectCode")
    object_name = named_inputs.get("object_name") or named_inputs.get("objectName")
    observation_date = named_inputs.get("observation_date") or named_inputs.get("observationDate")
    url = named_inputs.get("url")
    source = named_inputs.get("source") or args.source

    if len(positional_inputs) >= 4:
        project_code, object_name, url, observation_date = positional_inputs[:4]
    elif len(positional_inputs) == 1:
        project_code, object_name, url, observation_date = None, None, positional_inputs[0], None
    elif source:
        project_code, object_name, url, observation_date = None, None, source, None
    elif url:
        project_code, object_name, url, observation_date = None, None, url, None
    else:
        raise ValueError(
            "Provide either four values (project_code object_name url observation_date), "
            "a single source path/URL, or use --source."
        )

    return project_code, object_name, url, observation_date


def is_remote_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"}


def parse_mjd_to_date(value: str) -> str:
    try:
        mjd = float(value)
    except ValueError:
        return None
    try:
        return (datetime(1858, 11, 17) + timedelta(days=mjd)).date().isoformat()
    except OverflowError:
        return None


def download_remote_files(url: str, target_dir: Path, extensions=None) -> None:
    file_list = get_all_files_from_directory(url, base_url=url)
    if not file_list:
        raise RuntimeError(f"No files found for remote directory download at {url}")

    filtered_files = []
    if extensions is not None:
        extensions = {ext.lower() for ext in extensions}
        for relative, item_url in file_list:
            if Path(relative).suffix.lower() in extensions:
                filtered_files.append((relative, item_url))
        if filtered_files:
            file_list = filtered_files

    for relative_path, file_url in file_list:
        destination = target_dir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(file_url, str(destination))


def infer_metadata_from_remote_url(url: str) -> dict:
    parsed = urlparse(url)
    path_parts = [part for part in parsed.path.split("/") if part]
    project_code = None
    observation_date = None
    object_name = None

    for part in path_parts:
        match = re.search(r"\b(\d{2}[A-Z]-\d{3})\b", part)
        if match and project_code is None:
            project_code = match.group(1)
            break

    if is_remote_url(url):
        if path_parts and path_parts[-1].startswith("observation"):
            observation_dir_url = url
        else:
            obs_info = find_first_observation_dir(url)
            observation_dir_url = obs_info[1] if obs_info else None
            if obs_info and project_code is None:
                obs_parsed = urlparse(observation_dir_url)
                obs_parts = [part for part in obs_parsed.path.split("/") if part]
                for part in obs_parts:
                    if re.match(r"^\d{2}[A-Z]-\d{3}$", part):
                        project_code = part
                        break

        if observation_dir_url:
            temp_dir_name = None
            try:
                with tempfile.TemporaryDirectory() as temp_dir_name:
                    temp_dir = Path(temp_dir_name)
                    remote_metadata_dir = temp_dir / "remote_metadata"
                    remote_metadata_dir.mkdir(parents=True, exist_ok=True)
                    download_remote_files(observation_dir_url, remote_metadata_dir, extensions={".xml"})
                    metadata = run_metadata_scraper(Path(__file__).resolve().parent, remote_metadata_dir, project_code_override=project_code)
                    metadata_project_code = metadata.get("project_code")
                    metadata_object_name = metadata.get("object_name")
                    metadata_observation_date = metadata.get("observation_date")
                    if not project_code and metadata_project_code and metadata_project_code != "unknown":
                        project_code = metadata_project_code
                    if metadata_object_name and metadata_object_name != "unknown":
                        object_name = metadata_object_name
                    if not observation_date and metadata_observation_date and metadata_observation_date != "unknown":
                        observation_date = metadata_observation_date
            except Exception as exc:
                print(f"Warning: Remote metadata extraction failed: {exc}")
            finally:
                if temp_dir_name:
                    temp_path = Path(temp_dir_name)
                    if temp_path.exists():
                        shutil.rmtree(temp_path, ignore_errors=True)

    try:
        with urllib.request.urlopen(url) as response:
            html = response.read().decode("utf-8", errors="ignore")
    except Exception:
        html = None

    if html:
        links = re.findall(r'href=["\']([^"\']+)["\']', html)
        for link in links:
            clean_link = link.rstrip("/")
            if clean_link in {".", "..", ""}:
                continue
            if project_code is None:
                match = re.search(r"\b(\d{2}[A-Z]-\d{3})\b", clean_link)
                if match:
                    project_code = match.group(1)
            if observation_date is None:
                obs_match = re.search(r"observation\.(\d+(?:\.\d+)?)", clean_link)
                if obs_match:
                    observation_date = parse_mjd_to_date(obs_match.group(1))
            if project_code and observation_date:
                break

    if observation_date is None:
        for part in path_parts:
            obs_match = re.search(r"observation\.(\d+(?:\.\d+)?)", part)
            if obs_match:
                observation_date = parse_mjd_to_date(obs_match.group(1))
                break

    if object_name is None:
        object_name = "unknown"

    return {
        "project_code": project_code or "unknown",
        "object_name": object_name or "unknown",
        "observation_date": observation_date or "unknown",
    }


def run_metadata_scraper(script_dir: Path, source_path: Path, project_code_override: str = None) -> dict:
    metadata_script = script_dir / "metadata-scraper-CB.py"
    legacy_metadata_script = script_dir / "metadata-scrapper-CB.py"
    if metadata_script.exists():
        selected_script = metadata_script
    elif legacy_metadata_script.exists():
        selected_script = legacy_metadata_script
    else:
        raise FileNotFoundError(f"Could not find metadata-scraper-CB.py at {metadata_script}")

    metadata_cmd = [
        sys.executable,
        str(selected_script),
        str(source_path),
        "--output-format",
        "json",
    ]
    if project_code_override:
        metadata_cmd.extend(["--project-code", project_code_override])

    print(f"Inferring CB metadata from {selected_script.name}:")
    print(" ".join(metadata_cmd))

    result = subprocess.run(
        metadata_cmd,
        cwd=script_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise RuntimeError(stderr or f"{selected_script.name} failed with code {result.returncode}")

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Could not parse {selected_script.name} output: {exc}\nOutput:\n{result.stdout}") from exc


def infer_metadata_from_source(script_dir: Path, source: str) -> dict:
    source_value = source.strip()
    if not source_value:
        raise ValueError("No source path or URL provided for metadata inference.")

    if is_remote_url(source_value):
        print(f"Inferring CB metadata from remote URL without downloading the full dataset: {source_value}")
        return infer_metadata_from_remote_url(source_value)

    source_path = Path(source_value).expanduser()
    if not source_path.exists():
        raise FileNotFoundError(
            f"Could not find source path for metadata inference: {source_path}. "
            "Provide a local path to the CB dataset or pass the metadata values explicitly."
        )

    return run_metadata_scraper(script_dir, source_path)


def run_build(script_dir: Path, project_code: str, object_name: str, url: str, observation_date: str, args: argparse.Namespace) -> None:
    build_script = script_dir / "build_CB.py"
    if not build_script.exists():
        raise FileNotFoundError(f"Could not find build_CB.py at {build_script}")

    build_cmd = [
        sys.executable,
        str(build_script),
        project_code,
        object_name,
        url,
        observation_date,
        "--cb",
        args.cb,
    ]
    if args.temp_dir:
        build_cmd.extend(["--temp-dir", args.temp_dir])
    if args.verbose:
        build_cmd.append("--verbose")

    print("Running build step:")
    print(" ".join(build_cmd))
    if args.dry_run:
        return

    subprocess.run(build_cmd, cwd=script_dir, check=True)


def run_prep(script_dir: Path, workdir: Path, args: argparse.Namespace) -> None:
    prep_script = workdir / "prep-CB-for-calibration.py"
    if not prep_script.exists():
        raise FileNotFoundError(f"Could not find prep script at {prep_script}")

    prep_cmd = [sys.executable, str(prep_script.resolve())]
    print("Running CB prep script to generate SLURM scripts:")
    print(" ".join(prep_cmd))
    if args.dry_run:
        return

    subprocess.run(prep_cmd, cwd=workdir, check=True)


def run_submit(workdir: Path, args: argparse.Namespace) -> None:
    submit_script = workdir / "submit-CB-for-calibration.py"
    if not submit_script.exists():
        raise FileNotFoundError(f"Could not find submit script at {submit_script}")

    submit_cmd = [sys.executable, str(submit_script.resolve())]
    if args.submit_dry_run:
        submit_cmd.append("--dry-run")
    if args.submit_sleep_seconds is not None:
        submit_cmd.extend(["--sleep-seconds", str(args.submit_sleep_seconds)])

    print("Submitting CB job(s):")
    print(" ".join(submit_cmd))
    if args.dry_run:
        return

    subprocess.run(submit_cmd, cwd=workdir, check=True)


def main() -> None:
    args = parse_args()
    script_dir = Path(__file__).resolve().parent

    named_inputs, positional_inputs = parse_named_inputs(args.inputs)
    if args.source:
        named_inputs.setdefault("source", args.source)

    project_code, object_name, url, observation_date = collect_resolved_inputs(args, named_inputs, positional_inputs)
    if not project_code or not object_name or not observation_date:
        source_value = url or named_inputs.get("source") or args.source
        if not source_value:
            raise ValueError("A source path/URL is required when the metadata values are not supplied explicitly.")

        metadata = infer_metadata_from_source(script_dir, source_value)
        project_code = project_code or metadata.get("project_code")
        object_name = object_name or metadata.get("object_name")
        observation_date = observation_date or metadata.get("observation_date")

    if project_code == "unknown":
        project_code = None
    if object_name == "unknown":
        object_name = None
    if observation_date == "unknown":
        observation_date = None

    if not project_code or not object_name or not observation_date or not url:
        raise ValueError(
            "Could not resolve project_code, object_name, observation_date, and url. "
            "Supply them explicitly or point --source at a local dataset."
        )

    print(
        f"Resolved CB metadata: project_code={project_code}, object_name={object_name}, "
        f"observation_date={observation_date}, url={url}"
    )

    workdir = compute_workdir(project_code, object_name, observation_date)
    run_build(script_dir, project_code, object_name, url, observation_date, args)

    if args.dry_run:
        print("Dry run complete; prep and submit steps were not executed.")
        return

    if not workdir.exists():
        raise FileNotFoundError(f"Expected workdir not found after build: {workdir}")

    run_prep(script_dir, workdir, args)

    if args.skip_submit:
        print("Skipped submission as requested.")
        return

    run_submit(workdir, args)

    print(f"CB workflow completed. Workdir is ready at: {workdir.resolve()}")


if __name__ == "__main__":
    main()
