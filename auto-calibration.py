#!/usr/bin/env python3

import argparse
import subprocess
import sys
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Orchestrate CB build/prep and ASC auto-selfcal preparation using the CB .ms output."
        )
    )
    parser.add_argument("project_code", help="Project code, e.g. 23A-241")
    parser.add_argument("object_name", help="Object name, e.g. AT2019ehz")
    parser.add_argument("cb_input", nargs="?", help="URL or local path to the CB dataset when not skipping CB build/prep")
    parser.add_argument("--observation-date", help="Observation date, e.g. 2023-07-22")
    parser.add_argument("--cb-url", dest="cb_url", help="URL or local path to the CB dataset when not skipping CB build/prep")
    parser.add_argument("--cb-workdir", help="Existing CB working directory to use instead of running build/prep")
    parser.add_argument("--skip-cb", action="store_true", help="Skip CB build/prep and use --cb-workdir directly")
    parser.add_argument("--cb-template", default="CB", help="Path to the CB template directory")
    parser.add_argument("--asc-template", default="ASC", help="Path to the ASC template directory")
    parser.add_argument("--cb-temp-dir", help="Optional temporary directory for CB downloads and extraction")

    parser.add_argument(
        "--cb-submit",
        action="store_true",
        help="Submit CB batch jobs after build/prep. By default the wrapper skips CB submission.",
    )
    parser.add_argument(
        "--cb-submit-dry-run",
        action="store_true",
        help="When submitting CB jobs, print sbatch commands instead of executing them.",
    )
    parser.add_argument(
        "--cb-submit-sleep-seconds",
        type=int,
        help="Seconds to wait between CB sbatch submissions.",
    )
    parser.add_argument(
        "--cb-dry-run",
        action="store_true",
        help="Dry-run the CB workflow without executing build/prep/submission.",
    )

    parser.add_argument("--asc-source-name", help="Source name to write into ASC prep script")
    parser.add_argument(
        "--asc-split-band",
        default="both",
        choices=["whole", "halves", "both"],
        help="Split band strategy for ASC prep.",
    )
    parser.add_argument(
        "--asc-use-single-band",
        action="store_true",
        help="Set use_single_band=True in ASC prep.",
    )
    parser.add_argument(
        "--asc-single-band",
        default="EVLA_C",
        help="Single band to use when asc-use-single-band is set.",
    )
    parser.add_argument(
        "--asc-use-single-freq",
        action="store_true",
        help="Set use_single_freq=True in ASC prep.",
    )
    parser.add_argument(
        "--asc-single-freq",
        type=int,
        default=9,
        help="Single frequency to use when asc-use-single-freq is set.",
    )
    parser.add_argument(
        "--asc-a-config",
        action="store_true",
        help="Enable A_config in the ASC prep script.",
    )
    parser.add_argument(
        "--asc-auto-sc-dir",
        help="Optional auto_selfcal repository path for ASC prep.",
    )
    parser.add_argument(
        "--asc-casa-executable",
        default="casa",
        help="CASA executable to use when ASC launches CASA non-interactively.",
    )
    parser.add_argument(
        "--asc-no-casa",
        action="store_true",
        help="Do not launch CASA for ASC prep; only patch the prep script.",
    )
    parser.add_argument(
        "--asc-skip-submit",
        action="store_true",
        help="Do not submit ASC batch jobs after CASA prep.",
    )
    parser.add_argument(
        "--asc-dry-run",
        action="store_true",
        help="Dry-run the ASC workflow without executing CASA or submission.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry-run the combined workflow and print CB/ASC commands instead of executing them.",
    )
    return parser.parse_args()


def compute_cb_workdir(project_code: str, object_name: str, observation_date: str) -> Path:
    return Path(f"working.{project_code}.{object_name}.{observation_date}")


def is_ms_dir(path: Path) -> bool:
    if not path.is_dir():
        return False
    if path.suffix == ".ms":
        return True
    folder_names = {child.name.upper() for child in path.iterdir() if child.is_dir()}
    return bool(folder_names & {"FIELD", "MAIN", "ANTENNA", "SOURCE", "SPECTRAL_WINDOW", "OBSERVATION"})


def find_ms_directory(root_dir: Path) -> Path:
    root_dir = Path(root_dir)
    if is_ms_dir(root_dir):
        return root_dir

    for child in sorted(root_dir.iterdir()):
        if is_ms_dir(child):
            return child

    candidates = [p for p in root_dir.rglob("*.ms") if p.is_dir()]
    return candidates[0] if candidates else None


def infer_metadata_from_workdir(cb_workdir: Path):
    cb_workdir = Path(cb_workdir)
    name = cb_workdir.name
    if name.startswith("working."):
        parts = name.split(".", 3)
        if len(parts) == 4:
            _, project_code, object_name, observation_date = parts
            return project_code, object_name, observation_date
    return None


def run_subprocess(command, cwd: Path) -> None:
    print("Running:")
    print(" ".join(str(arg) for arg in command))
    subprocess.run(command, cwd=cwd, check=True)


def run_cb_workflow(args: argparse.Namespace) -> Path:
    script_dir = Path(__file__).resolve().parent
    cb_script = script_dir / "run_build_and_prep_CB.py"
    if not cb_script.exists():
        raise FileNotFoundError(f"Could not find CB wrapper script: {cb_script}")

    if args.skip_cb:
        if not args.cb_workdir:
            sys.exit("Error: --skip-cb requires --cb-workdir to be provided.")
        cb_workdir = Path(args.cb_workdir).expanduser()
        if not cb_workdir.exists():
            sys.exit(f"Error: CB workdir not found: {cb_workdir}")

        metadata = infer_metadata_from_workdir(cb_workdir)
        if metadata:
            project_code, object_name, observation_date = metadata
            if not args.project_code:
                args.project_code = project_code
            if not args.object_name:
                args.object_name = object_name
            if not args.observation_date:
                args.observation_date = observation_date

        if not args.observation_date:
            sys.exit("Error: --observation-date is required when skipping CB build/prep unless it can be inferred from --cb-workdir.")

        print(f"Skipping CB build/prep and using existing workdir: {cb_workdir}")
        return cb_workdir

    cb_url = args.cb_input or args.cb_url
    if not cb_url:
        sys.exit("Error: cb_input or --cb-url must be provided unless --skip-cb is used.")
    if not args.observation_date:
        sys.exit("Error: --observation-date is required for CB build/prep.")

    cb_workdir = compute_cb_workdir(args.project_code, args.object_name, args.observation_date)
    cmd = [sys.executable, str(cb_script), args.project_code, args.object_name, cb_url, args.observation_date]
    cmd.extend(["--cb", args.cb_template])
    if args.cb_temp_dir:
        cmd.extend(["--temp-dir", args.cb_temp_dir])
    if not args.cb_submit:
        cmd.append("--skip-submit")
    if args.cb_submit_dry_run:
        cmd.append("--submit-dry-run")
    if args.cb_submit_sleep_seconds is not None:
        cmd.extend(["--submit-sleep-seconds", str(args.cb_submit_sleep_seconds)])
    if args.cb_dry_run or args.dry_run:
        cmd.append("--dry-run")

    if args.dry_run:
        print("CB dry run enabled; the following command would be executed:")
        print(" ".join(str(arg) for arg in cmd))
        return cb_workdir

    run_subprocess(cmd, cwd=script_dir)

    if not cb_workdir.exists():
        raise FileNotFoundError(f"Expected CB workdir not found after build: {cb_workdir}")
    return cb_workdir


def run_asc_workflow(args: argparse.Namespace, ms_path: Path) -> None:
    script_dir = Path(__file__).resolve().parent
    asc_script = script_dir / "run_build_and_prep_ASC.py"
    if not asc_script.exists():
        raise FileNotFoundError(f"Could not find ASC wrapper script: {asc_script}")

    cmd = [sys.executable, str(asc_script), args.project_code, args.object_name, args.observation_date]
    cmd.extend(["--ms-path", str(ms_path)])
    cmd.extend(["--asc", args.asc_template])
    if args.asc_source_name:
        cmd.extend(["--source_name", args.asc_source_name])
    if args.asc_split_band:
        cmd.extend(["--split_band", args.asc_split_band])
    if args.asc_use_single_band:
        cmd.append("--use_single_band")
        cmd.extend(["--single_band", args.asc_single_band])
    if args.asc_use_single_freq:
        cmd.append("--use_single_freq")
        cmd.extend(["--single_freq", str(args.asc_single_freq)])
    if args.asc_a_config:
        cmd.append("--a_config")
    if args.asc_auto_sc_dir:
        cmd.extend(["--auto_sc_dir", args.asc_auto_sc_dir])
    if args.asc_no_casa:
        cmd.append("--run-casa")
    if args.asc_skip_submit:
        cmd.append("--skip-submit")
    if args.asc_dry_run or args.dry_run:
        cmd.append("--dry-run")
    if args.asc_casa_executable != "casa":
        cmd.extend(["--casa-executable", args.asc_casa_executable])

    if args.dry_run:
        print("ASC dry run enabled; the following command would be executed:")
        print(" ".join(str(arg) for arg in cmd))
        return

    run_subprocess(cmd, cwd=script_dir)


def main() -> None:
    args = parse_args()

    if args.dry_run:
        args.cb_dry_run = True
        args.asc_dry_run = True

    if args.skip_cb and not args.cb_workdir:
        sys.exit("Error: --skip-cb requires --cb-workdir.")

    cb_workdir = run_cb_workflow(args)

    if args.dry_run:
        print("Dry-run complete. No ASC workflow was executed because the wrapper is in dry-run mode.")
        return

    ms_path = find_ms_directory(cb_workdir)
    if ms_path is None:
        sys.exit(f"Error: Could not locate a .ms measurement set inside the CB workdir {cb_workdir}.")

    print(f"Found CB measurement set for ASC input: {ms_path}")
    run_asc_workflow(args, ms_path)
    print("Combined auto-calibration workflow completed successfully.")


if __name__ == "__main__":
    main()
