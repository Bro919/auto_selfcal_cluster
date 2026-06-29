#!/usr/bin/env python3

import argparse
import json
import subprocess
import sys
from pathlib import Path


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
            "source path/URL to let metadata-scrapper-CB.py infer the metadata."
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
    return parser.parse_args()


def compute_workdir(project_code: str, object_name: str, observation_date: str) -> Path:
    return Path(f"working.{project_code}.{object_name}.{observation_date}")


def collect_resolved_inputs(args: argparse.Namespace) -> tuple[str, str, str, str]:
    if len(args.inputs) >= 4:
        project_code, object_name, url, observation_date = args.inputs[:4]
    elif len(args.inputs) == 1:
        project_code, object_name, url, observation_date = None, None, args.inputs[0], None
    elif args.source:
        project_code, object_name, url, observation_date = None, None, args.source, None
    else:
        raise ValueError(
            "Provide either four values (project_code object_name url observation_date), "
            "a single source path/URL, or use --source."
        )

    return project_code, object_name, url, observation_date


def infer_metadata_from_source(script_dir: Path, source: str) -> dict:
    metadata_script = script_dir / "metadata-scrapper-CB.py"
    if not metadata_script.exists():
        raise FileNotFoundError(f"Could not find metadata-scrapper-CB.py at {metadata_script}")

    source_path = Path(source).expanduser()
    if not source_path.exists():
        raise FileNotFoundError(
            f"Could not find source path for metadata inference: {source_path}. "
            "Provide a local path to the CB dataset or pass the metadata values explicitly."
        )

    metadata_cmd = [
        sys.executable,
        str(metadata_script),
        str(source_path),
        "--output-format",
        "json",
    ]
    print("Inferring CB metadata from metadata-scrapper-CB.py:")
    print(" ".join(metadata_cmd))

    result = subprocess.run(metadata_cmd, cwd=script_dir, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise RuntimeError(stderr or f"metadata-scrapper-CB.py failed with code {result.returncode}")

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Could not parse metadata-scrapper-CB.py output: {exc}\nOutput:\n{result.stdout}") from exc


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

    project_code, object_name, url, observation_date = collect_resolved_inputs(args)
    if not project_code or not object_name or not observation_date:
        if not url:
            raise ValueError("A source path/URL is required when the metadata values are not supplied explicitly.")

        metadata = infer_metadata_from_source(script_dir, url)
        project_code = project_code or metadata.get("project_code")
        object_name = object_name or metadata.get("object_name")
        observation_date = observation_date or metadata.get("observation_date")

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
