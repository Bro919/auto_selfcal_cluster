#!/usr/bin/env python3

import argparse
import re
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
    parser.add_argument(
        "--no-chain-afterok",
        action="store_true",
        help="Disable dependency chaining between scripts in the batch list.",
    )
    return parser.parse_args()


def extract_job_id(sbatch_output: str) -> str:
    match = re.search(r"Submitted\s+batch\s+job\s+(\d+)", sbatch_output)
    if not match:
        return ""
    return match.group(1)


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

    chain_afterok = not args.no_chain_afterok
    previous_job_id = ""

    for index, script_path_str in enumerate(scripts):
        script_path = Path(script_path_str)
        if not script_path.exists():
            print(f"Script does not exist: {script_path}", file=sys.stderr)
            exit_code = 1
            continue

        command = ["sbatch"]
        dependency_text = ""
        if chain_afterok and index > 0:
            if not previous_job_id and not args.dry_run:
                print(
                    f"Could not determine previous job id; skipping dependent submit for {script_path}",
                    file=sys.stderr,
                )
                exit_code = 1
                break
            if args.dry_run and not previous_job_id:
                dependency_text = "<previous_job_id>"
            else:
                dependency_text = previous_job_id
            command.extend(["--dependency", f"afterok:{dependency_text}"])

        command.append(str(script_path))

        if chain_afterok and dependency_text:
            print(f"Submitting (afterok:{dependency_text}): {script_path}")
        else:
            print(f"Submitting: {script_path}")

        if args.dry_run:
            print(" ".join(command))
        else:
            try:
                result = subprocess.run(
                    command,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    universal_newlines=True,
                )
                stdout_text = result.stdout.strip()
                stderr_text = result.stderr.strip()
                if stdout_text:
                    print(stdout_text)
                if stderr_text:
                    print(stderr_text, file=sys.stderr)

                submitted_job_id = extract_job_id(stdout_text)
                if submitted_job_id:
                    previous_job_id = submitted_job_id
                elif chain_afterok:
                    print(
                        f"Warning: Could not parse job id from sbatch output for {script_path}",
                        file=sys.stderr,
                    )
                    previous_job_id = ""
            except subprocess.CalledProcessError as exc:
                print(f"Failed to submit {script_path}: {exc}", file=sys.stderr)
                exit_code = 1
                if chain_afterok:
                    break
        if args.sleep_seconds > 0:
            time.sleep(args.sleep_seconds)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
