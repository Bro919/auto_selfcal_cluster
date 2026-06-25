#!/usr/bin/env python3

import argparse
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
    parser.add_argument("project_code", help="Project code, e.g. 23A-241")
    parser.add_argument("object_name", help="Object name, e.g. AT2019ehz")
    parser.add_argument("url", help="URL or local path to the CB dataset")
    parser.add_argument("observation_date", help="Observation date, e.g. 2023-07-22")
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


def run_build(script_dir: Path, args: argparse.Namespace) -> None:
    build_script = script_dir / "build_CB.py"
    if not build_script.exists():
        raise FileNotFoundError(f"Could not find build_CB.py at {build_script}")

    build_cmd = [
        sys.executable,
        str(build_script),
        args.project_code,
        args.object_name,
        args.url,
        args.observation_date,
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

    prep_cmd = [sys.executable, str(prep_script)]
    print("Running CB prep script to generate SLURM scripts:")
    print(" ".join(prep_cmd))
    if args.dry_run:
        return

    subprocess.run(prep_cmd, cwd=workdir, check=True)


def run_submit(workdir: Path, args: argparse.Namespace) -> None:
    submit_script = workdir / "submit-CB-for-calibration.py"
    if not submit_script.exists():
        raise FileNotFoundError(f"Could not find submit script at {submit_script}")

    submit_cmd = [sys.executable, str(submit_script)]
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
    workdir = compute_workdir(args.project_code, args.object_name, args.observation_date)

    run_build(script_dir, args)

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
