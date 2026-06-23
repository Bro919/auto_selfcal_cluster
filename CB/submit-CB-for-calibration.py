#!/usr/bin/env python3

import argparse
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_BATCH_LIST_FILE = "batch_files_list.txt"
DEFAULT_SLEEP_SECONDS = 10


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Submit SBATCH scripts listed in a batch file for CB CASA jobs."
    )
    parser.add_argument(
        "--batch-list-file",
        default=DEFAULT_BATCH_LIST_FILE,
        help=f"Path to file containing one SBATCH script path per line (default: {DEFAULT_BATCH_LIST_FILE}).",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=int,
        default=DEFAULT_SLEEP_SECONDS,
        help=f"Seconds to wait between sbatch submissions (default: {DEFAULT_SLEEP_SECONDS}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the sbatch commands instead of executing them.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    batch_list_path = Path(args.batch_list_file).expanduser().resolve()

    if not batch_list_path.exists():
        print(f"Error: batch list file not found: {batch_list_path}", file=sys.stderr)
        return 1

    with batch_list_path.open("r", encoding="utf-8") as batch_file:
        scripts = [line.strip() for line in batch_file if line.strip()]

    if not scripts:
        print(f"Error: no SBATCH scripts found in {batch_list_path}", file=sys.stderr)
        return 1

    exit_code = 0

    for script_path_str in scripts:
        script_path = Path(script_path_str)
        if not script_path.exists():
            print(f"Script does not exist: {script_path}", file=sys.stderr)
            exit_code = 1
            continue

        print(f"Submitting: {script_path}")
        if args.dry_run:
            print(f"sbatch {script_path}")
        else:
            try:
                subprocess.run(["sbatch", str(script_path)], check=True)
            except subprocess.CalledProcessError as exc:
                print(f"Failed to submit {script_path}: {exc}", file=sys.stderr)
                exit_code = 1
        if args.sleep_seconds > 0:
            time.sleep(args.sleep_seconds)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
