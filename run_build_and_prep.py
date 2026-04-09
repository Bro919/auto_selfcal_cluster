import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional


def parse_args():
    parser = argparse.ArgumentParser(
        description="Build the auto_selfcal workdir, patch the prep script, and optionally launch CASA interactively."
    )
    parser.add_argument("project_code", help="Project code, e.g. 23A-241")
    parser.add_argument("object_name", help="Object name, e.g. AT2019ehz")
    parser.add_argument("url", help="URL to download from")
    parser.add_argument("observation_date", help="Observation date, e.g. 2023-07-22")
    parser.add_argument("--asc", default="ASC", help="ASC template directory or path (default: ASC)")
    parser.add_argument("--a_config", action="store_true", help="Enable A_config in the prep script")

    parser.add_argument("--source_name", default=None, help="Source name to write into prep script (defaults to object_name)")
    parser.add_argument("--split_band", default="both", choices=["whole", "halves", "both"], help="Split band strategy for prep script")
    parser.add_argument("--use_single_band", action="store_true", help="Set use_single_band=True in prep script")
    parser.add_argument("--single_band", default="EVLA_C", help="Single band to use when use_single_band=True")
    parser.add_argument("--use_single_freq", action="store_true", help="Set use_single_freq=True in prep script")
    parser.add_argument("--single_freq", type=int, default=9, help="Single frequency to use when use_single_freq=True")
    parser.add_argument("--auto_sc_dir", default=None, help="Optional path to auto_selfcal repo directory for prep script")

    parser.add_argument("--run-casa", action="store_true", help="Launch interactive CASA after building the workdir")
    parser.add_argument("--casa-executable", default="casa", help="CASA executable to use when launching interactive CASA")
    parser.add_argument("--dry-run", action="store_true", help="Show the build command and patching actions without executing them")
    return parser.parse_args()


def compute_workdir(project_code: str, object_name: str, observation_date: str) -> Path:
    return Path(f"{project_code}.{object_name}.{observation_date}")


def patch_prep_script(
    prep_path: Path,
    measurement_set: str,
    source_name: str,
    split_band: str,
    use_single_band: bool,
    single_band: str,
    use_single_freq: bool,
    single_freq: int,
    a_config: bool,
    auto_sc_dir: Optional[str],
):
    if not prep_path.exists():
        raise FileNotFoundError(f"Prep script not found at {prep_path}")

    patterns = {
        "measurement_set": rf'^measurement_set\s*=.*$',
        "source_name": rf'^source_name\s*=.*$',
        "split_band": rf'^split_band\s*=.*$',
        "use_single_band": rf'^use_single_band\s*=.*$',
        "single_band": rf'^single_band\s*=.*$',
        "use_single_freq": rf'^use_single_freq\s*=.*$',
        "single_freq": rf'^single_freq\s*=.*$',
        "A_config": rf'^A_config\s*=.*$',
        "auto_sc_files_directory": rf'^auto_sc_files_directory\s*=.*$',
    }

    replacements = {
        "measurement_set": f'measurement_set = "{measurement_set}"',
        "source_name": f'source_name = "{source_name}"',
        "split_band": f'split_band = "{split_band}"',
        "use_single_band": f'use_single_band = {str(use_single_band)}',
        "single_band": f'single_band = "{single_band}"',
        "use_single_freq": f'use_single_freq = {str(use_single_freq)}',
        "single_freq": f'single_freq = {single_freq}',
        "A_config": f'A_config = {str(a_config)}  # Set to True to use special resources for L band',
    }

    text = prep_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    updated_lines = []
    found_keys = set()

    for line in lines:
        replaced = False
        for key, pattern in patterns.items():
            if re.match(pattern, line):
                if key == "auto_sc_files_directory":
                    if auto_sc_dir is None:
                        continue
                    replacement = f'auto_sc_files_directory = "{auto_sc_dir}"'
                else:
                    replacement = replacements[key]
                updated_lines.append(replacement)
                found_keys.add(key)
                replaced = True
                break
        if not replaced:
            updated_lines.append(line)

    if auto_sc_dir is not None and "auto_sc_files_directory" not in found_keys:
        insert_idx = 0
        for idx, line in enumerate(updated_lines):
            if line.startswith("#") or line.strip() == "":
                continue
            insert_idx = idx
            break
        updated_lines.insert(insert_idx, f'auto_sc_files_directory = "{auto_sc_dir}"')

    if "measurement_set" not in found_keys:
        raise RuntimeError("Could not find measurement_set assignment in prep script")

    prep_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")


def main():
    args = parse_args()
    script_dir = Path(__file__).resolve().parent
    workdir = compute_workdir(args.project_code, args.object_name, args.observation_date)
    if args.source_name is None:
        source_name = args.object_name
    else:
        source_name = args.source_name
    measurement_set_name = f"{args.project_code}.{args.object_name}.{args.observation_date}.ms"

    build_cmd = [
        sys.executable,
        str(script_dir / "build_dir.py"),
        args.project_code,
        args.object_name,
        args.url,
        args.observation_date,
        "--asc",
        args.asc,
    ]
    if args.a_config:
        build_cmd.append("--a_config")

    print("Build command:")
    print(" ".join(build_cmd))

    if args.dry_run:
        print("Dry run enabled. Exiting before execution.")
        return

    subprocess.run(build_cmd, cwd=script_dir, check=True)

    prep_script_path = workdir / "prep-ms-for-auto-selfcal.py"
    print(f"Patching prep script at {prep_script_path}")
    patch_prep_script(
        prep_script_path,
        measurement_set=measurement_set_name,
        source_name=source_name,
        split_band=args.split_band,
        use_single_band=args.use_single_band,
        single_band=args.single_band,
        use_single_freq=args.use_single_freq,
        single_freq=args.single_freq,
        a_config=args.a_config,
        auto_sc_dir=args.auto_sc_dir,
    )

    print("Prep script patched successfully.")
    print(f"Workdir ready at: {workdir.resolve()}")
    print("Next step:")
    print(f"  cd {workdir}")
    print("  execfile('prep-ms-for-auto-selfcal.py')")

    if args.run_casa:
        print("Launching interactive CASA in the workdir...")
        subprocess.run([args.casa_executable], cwd=workdir)
    else:
        print("To launch CASA manually, run:")
        print(f"  cd {workdir}")
        print(f"  {args.casa_executable}")


if __name__ == "__main__":
    main()
