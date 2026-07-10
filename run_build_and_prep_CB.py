#!/usr/bin/env python3

import argparse
import json
import logging
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

from build_CB import find_first_observation_dir, get_all_files_from_directory


def configure_logging(verbose: bool) -> logging.Logger:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="[%(levelname)s] %(message)s")
    return logging.getLogger("run_build_and_prep_CB")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build the CB workdir, generate the SLURM batch script, "
            "and optionally submit the job via sbatch."
        )
    )
    parser.add_argument("project_code", nargs="?", help="Project code, e.g. 23A-241")
    parser.add_argument("object_name", nargs="?", help="Object name, e.g. AT2019ehz")
    parser.add_argument("observation_date", nargs="?", help="Observation date, e.g. 2023-07-22")
    parser.add_argument(
        "url_arg",
        nargs="?",
        help="Optional URL/path argument, either raw value or url=<value> after positional args",
    )
    parser.add_argument("--url", help="URL or local path to source dataset")
    parser.add_argument(
        "--source",
        help="Alias for --url; local path or URL used for metadata inference when needed.",
    )
    parser.add_argument("--cb", default="CB", help="Path to CB template directory (default: CB)")
    parser.add_argument("--temp-dir", help="Optional temporary directory for downloads and extraction")

    parser.add_argument("--skip-submit", action="store_true", help="Build and prepare the job, but do not submit")
    parser.add_argument(
        "--submit-dry-run",
        action="store_true",
        help="Print sbatch commands instead of executing them when submitting",
    )
    parser.add_argument(
        "--submit-sleep-seconds",
        type=int,
        default=None,
        help="Seconds to wait between sbatch submissions",
    )

    parser.add_argument("--dry-run", action="store_true", help="Show build/prep/submit commands without executing")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Reduce non-critical output noise in build_CB.py",
    )
    return parser.parse_args()


def compute_workdir(project_code: str, object_name: str, observation_date: str) -> Path:
    return Path(f"working.{project_code}.{object_name}.{observation_date}")


def parse_named_inputs(inputs: List[str]) -> Tuple[Dict[str, str], List[str]]:
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
    if re.match(r"^\d{4}-\d{2}-\d{2}$", str(value)):
        return True
    return bool(re.match(r"^\d{5,6}(?:\.\d+)?$", str(value)))


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
    if named_inputs.get("source") and not args.source:
        args.source = named_inputs["source"]

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

    # Backward compatibility with old single-source positional form.
    if (
        args.project_code
        and not args.object_name
        and not args.observation_date
        and not args.url_arg
        and not args.url
        and not named_inputs.get("project_code")
    ):
        args.url = args.project_code
        args.source = args.source or args.project_code
        args.project_code = None

    if args.source and not args.url:
        args.url = args.source
    if args.url and not args.source:
        args.source = args.url

    return args


def collect_resolved_inputs(
    args: argparse.Namespace,
    named_inputs: Optional[Dict[str, str]] = None,
    positional_inputs: Optional[List[str]] = None,
) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    del named_inputs, positional_inputs
    project_code = args.project_code
    object_name = args.object_name
    observation_date = args.observation_date
    url = args.url or args.source
    return project_code, object_name, url, observation_date


def is_remote_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"}


def parse_mjd_to_date(value: str) -> Optional[str]:
    try:
        mjd = float(value)
    except ValueError:
        return None

    try:
        return (datetime(1858, 11, 17) + timedelta(days=mjd)).date().isoformat()
    except OverflowError:
        return None


def run_checked(command: List[str], cwd: Path, logger: logging.Logger, description: str, dry_run: bool) -> None:
    logger.info("%s", description)
    logger.debug("Command: %s", " ".join(command))
    if dry_run:
        return

    try:
        subprocess.run(command, cwd=cwd, check=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"{description} failed (exit code {exc.returncode})")


def download_remote_files(url: str, target_dir: Path, extensions: Optional[set] = None) -> None:
    file_list = get_all_files_from_directory(url, base_url=url)
    if not file_list:
        raise RuntimeError(f"No files found for remote directory download at {url}")

    if extensions is not None:
        lowered = {ext.lower() for ext in extensions}
        filtered = [(rel, item_url) for rel, item_url in file_list if Path(rel).suffix.lower() in lowered]
        if filtered:
            file_list = filtered

    for relative_path, file_url in file_list:
        destination = target_dir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(file_url, str(destination))


def run_metadata_scraper(script_dir: Path, source_path: Path, project_code_override: Optional[str] = None) -> dict:
    metadata_script = script_dir / "metadata-scraper-CB.py"
    legacy_script = script_dir / "metadata-scrapper-CB.py"

    if metadata_script.exists():
        selected_script = metadata_script
    elif legacy_script.exists():
        selected_script = legacy_script
    else:
        raise FileNotFoundError("Could not find metadata-scraper-CB.py or metadata-scrapper-CB.py")

    command = [
        sys.executable,
        str(selected_script),
        str(source_path),
        "--output-format",
        "json",
    ]
    if project_code_override:
        command.extend(["--project-code", project_code_override])

    print(f"Inferring CB metadata from {selected_script.name}:")
    print(" ".join(command))

    result = subprocess.run(
        command,
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
        raise RuntimeError(f"Could not parse {selected_script.name} output: {exc}\nOutput:\n{result.stdout}")


def infer_metadata_from_remote_url(url: str, logger: logging.Logger) -> dict:
    parsed = urlparse(url)
    path_parts = [part for part in parsed.path.split("/") if part]

    project_code: Optional[str] = None
    observation_date: Optional[str] = None
    object_name: Optional[str] = None

    for part in path_parts:
        match = re.search(r"\b(\d{2}[A-Z]-\d{3})\b", part)
        if match:
            project_code = match.group(1)
            break

    observation_dir_url: Optional[str] = None
    if path_parts and path_parts[-1].startswith("observation"):
        observation_dir_url = url
    else:
        obs_info = find_first_observation_dir(url)
        observation_dir_url = obs_info[1] if obs_info else None
        if obs_info and project_code is None:
            obs_parsed = urlparse(str(observation_dir_url))
            obs_parts = [str(part) for part in str(obs_parsed.path).split("/") if part]
            for part in obs_parts:
                if re.match(r"^\d{2}[A-Z]-\d{3}$", part):
                    project_code = part
                    break

    if observation_dir_url:
        try:
            with tempfile.TemporaryDirectory() as temp_dir_name:
                temp_dir = Path(temp_dir_name)
                remote_metadata_dir = temp_dir / "remote_metadata"
                remote_metadata_dir.mkdir(parents=True, exist_ok=True)
                download_remote_files(observation_dir_url, remote_metadata_dir, extensions={".xml"})
                metadata = run_metadata_scraper(Path(__file__).resolve().parent, remote_metadata_dir, project_code)

                if not project_code and metadata.get("project_code") not in (None, "", "unknown"):
                    project_code = metadata.get("project_code")
                if metadata.get("object_name") not in (None, "", "unknown"):
                    object_name = metadata.get("object_name")
                if not observation_date and metadata.get("observation_date") not in (None, "", "unknown"):
                    observation_date = metadata.get("observation_date")
        except Exception as exc:
            logger.warning("Remote metadata extraction failed: %s", exc)

    try:
        with urllib.request.urlopen(url) as response:
            html = response.read().decode("utf-8", errors="ignore")
    except Exception:
        html = None

    if html:
        links = re.findall(r'href=["\']([^"\']+)["\']', html)
        for link in links:
            clean = link.rstrip("/")
            if clean in {".", "..", ""}:
                continue
            if project_code is None:
                match = re.search(r"\b(\d{2}[A-Z]-\d{3})\b", clean)
                if match:
                    project_code = match.group(1)
            if observation_date is None:
                obs_match = re.search(r"observation\.(\d+(?:\.\d+)?)", clean)
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

    return {
        "project_code": project_code or "unknown",
        "object_name": object_name or "unknown",
        "observation_date": observation_date or "unknown",
    }


def infer_metadata_from_source(script_dir: Path, source: str, logger: logging.Logger) -> dict:
    source_value = source.strip()
    if not source_value:
        raise ValueError("No source path or URL provided for metadata inference")

    if is_remote_url(source_value):
        logger.info("Inferring CB metadata from remote URL without full download")
        return infer_metadata_from_remote_url(source_value, logger)

    source_path = Path(source_value).expanduser()
    if not source_path.exists():
        raise FileNotFoundError(
            f"Could not find source path for metadata inference: {source_path}. "
            "Provide a local path or pass metadata values explicitly."
        )

    return run_metadata_scraper(script_dir, source_path)


def run_build(
    script_dir: Path,
    project_code: str,
    object_name: str,
    url: str,
    observation_date: str,
    args: argparse.Namespace,
    logger: logging.Logger,
) -> None:
    build_script = script_dir / "build_CB.py"
    if not build_script.exists():
        raise FileNotFoundError(f"Could not find build_CB.py at {build_script}")

    command = [
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
        command.extend(["--temp-dir", args.temp_dir])
    if args.verbose:
        command.append("--verbose")
    if args.quiet:
        command.append("--quiet")

    run_checked(command, script_dir, logger, "Running build step", args.dry_run)


def run_prep(workdir: Path, args: argparse.Namespace, logger: logging.Logger) -> None:
    prep_script = workdir / "prep-CB-for-calibration.py"
    if not prep_script.exists():
        raise FileNotFoundError(f"Could not find prep script at {prep_script}")

    command = [sys.executable, str(prep_script.resolve())]
    run_checked(command, workdir, logger, "Running CB prep script", args.dry_run)


def run_submit(workdir: Path, args: argparse.Namespace, logger: logging.Logger) -> None:
    submit_script = workdir / "submit-CB-for-calibration.py"
    if not submit_script.exists():
        raise FileNotFoundError(f"Could not find submit script at {submit_script}")

    command = [sys.executable, str(submit_script.resolve())]
    if args.submit_dry_run:
        command.append("--dry-run")
    if args.submit_sleep_seconds is not None:
        command.extend(["--sleep-seconds", str(args.submit_sleep_seconds)])

    run_checked(command, workdir, logger, "Submitting CB job(s)", args.dry_run)


def main() -> None:
    args = normalize_cli_inputs(parse_args())
    logger = configure_logging(args.verbose)
    logger.info("Starting CB build+prep runner")

    script_dir = Path(__file__).resolve().parent
    project_code, object_name, url, observation_date = collect_resolved_inputs(args)

    if not project_code or not object_name or not observation_date:
        source_value = args.source or url
        if not source_value:
            raise ValueError("A source path/URL is required when metadata values are not supplied explicitly.")

        metadata = infer_metadata_from_source(script_dir, source_value, logger)
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

    logger.info(
        "Resolved CB metadata: project_code=%s object_name=%s observation_date=%s",
        project_code,
        object_name,
        observation_date,
    )
    logger.debug("Resolved source URL/path: %s", url)

    workdir = compute_workdir(str(project_code), str(object_name), str(observation_date))

    run_build(script_dir, str(project_code), str(object_name), str(url), str(observation_date), args, logger)

    if args.dry_run:
        logger.info("Dry run complete; prep and submit were not executed")
        return

    if not workdir.exists():
        raise FileNotFoundError(f"Expected workdir not found after build: {workdir}")

    run_prep(workdir, args, logger)

    if args.skip_submit:
        logger.info("Skipped submission as requested")
        return

    run_submit(workdir, args, logger)
    logger.info("CB workflow completed. Workdir is ready at: %s", workdir.resolve())


if __name__ == "__main__":
    main()
