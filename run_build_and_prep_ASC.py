import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple, Union
from urllib.parse import urlparse


def parse_args():
    parser = argparse.ArgumentParser(
        description="Build the auto_selfcal workdir, patch the prep script, and optionally launch CASA non-interactively."
    )
    parser.add_argument("project_code", nargs='?', help="Project code, e.g. 23A-241")
    parser.add_argument("object_name", nargs='?', help="Object name, e.g. AT2019ehz")
    parser.add_argument("observation_date", nargs='?', help="Observation date, e.g. 2023-07-22")
    parser.add_argument(
        "url_arg",
        nargs='?',
        help="Optional URL argument, either raw URL or url=<value> after the positional args",
    )
    parser.add_argument("--url", help="URL to download from")
    parser.add_argument(
        "--ms-path",
        help="Path to a local measurement set directory, extracted SDM-BDF root, or a CB-style working directory for metadata extraction and local workdir creation",
    )
    parser.add_argument(
        "--source",
        help="Alias for --ms-path; use a local source path to let the ASC metadata scraper provide project code, object name, and observation date.",
    )
    parser.add_argument(
        "--use-ms-metadata",
        action="store_true",
        help="When metadata values are missing, extract them from the downloaded .ms or local MS path using the ASC metadata scraper.",
    )
    parser.add_argument("--asc", default="ASC", help="ASC template directory or path (default: ASC)")
    parser.add_argument("--a_config", action="store_true", help="Enable A_config in the prep script")

    parser.add_argument("--source_name", default=None, help="Source name to write into prep script (defaults to object_name)")
    parser.add_argument("--split_band", default="both", choices=["whole", "halves", "both"], help="Split band strategy for prep script")
    parser.add_argument("--use_single_band", action="store_true", help="Set use_single_band=True in prep script")
    parser.add_argument("--single_band", default="EVLA_C", help="Single band to use when use_single_band=True")
    parser.add_argument("--use_single_freq", action="store_true", help="Set use_single_freq=True in prep script")
    parser.add_argument("--single_freq", type=int, default=9, help="Single frequency to use when use_single_freq=True")
    parser.add_argument("--auto_sc_dir", default=None, help="Optional path to auto_selfcal repo directory for prep script")

    parser.add_argument(
        "--run-casa",
        action="store_false",
        help="Launch CASA non-interactively after building the workdir, execute the prep script, and optionally submit batch jobs",
    )
    parser.add_argument(
        "--skip-submit",
        action="store_true",
        help="Do not run submit_batch_of_batch_jobs.py after the prep script completes",
    )
    parser.add_argument(
        "--casa-executable",
        default="casa",
        help="CASA executable to use when launching CASA non-interactively",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the build command and patching actions without executing them",
    )
    return parser.parse_args()


def compute_workdir(project_code: str, object_name: str, observation_date: str) -> Path:
    return Path(f"{project_code}.{object_name}.{observation_date}")


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


def extract_project_code_from_url(url: str) -> Optional[str]:
    """Extract project code (e.g., 24A-322) from URL path."""
    if not url:
        return None
    parsed = urlparse(url)
    path_parts = [part for part in parsed.path.split("/") if part]
    for part in path_parts:
        match = re.search(r'\b(\d{2}[A-Z]-\d{3})\b', part)
        if match:
            return match.group(1)
    return None


def apply_extracted_metadata(
    workdir: Path,
    project_code: Optional[str] = None,
    object_name: Optional[str] = None,
    observation_date: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    metadata_file = workdir / ".extracted_metadata"
    if not metadata_file.exists():
        return project_code, object_name, observation_date

    values = {
        "project_code": project_code,
        "object_name": object_name,
        "observation_date": observation_date,
    }
    try:
        with metadata_file.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                if key in values and not values[key] in (None, "unknown"):
                    continue
                values[key] = value
    except Exception as exc:
        print(f"Warning: Could not read extracted metadata file: {exc}")

    if values["project_code"] not in (None, "unknown"):
        print(f"Using extracted project code from file: {values['project_code']}")

    return values["project_code"], values["object_name"], values["observation_date"]


def is_ms_dir(path: Path) -> bool:
    path = Path(path)
    if not path.is_dir():
        return False
    if path.suffix == ".ms":
        return True
    folder_names = {child.name.upper() for child in path.iterdir() if child.is_dir()}
    return bool(folder_names & {"FIELD", "MAIN", "ANTENNA", "SOURCE", "SPECTRAL_WINDOW", "OBSERVATION"})


def find_ms_directory(root_dir: Path) -> Path:
    if is_ms_dir(root_dir):
        return root_dir
    candidates = [p for p in root_dir.iterdir() if p.is_dir() and p.name.endswith('.ms')]
    if candidates:
        return candidates[0]
    candidates = [p for p in root_dir.rglob('*') if p.is_dir() and p.name.endswith('.ms')]
    return candidates[0] if candidates else None


def copy_tree(src: Path, dst: Path) -> None:
    src = Path(src)
    dst = Path(dst)
    if not src.exists():
        raise FileNotFoundError(f"Source path not found: {src}")
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        dest_item = dst / item.name
        if item.is_dir():
            shutil.copytree(str(item), str(dest_item))
        else:
            shutil.copy2(str(item), str(dest_item))


def resolve_local_measurement_set(input_path: Path) -> Path:
    if is_ms_dir(input_path):
        return input_path
    if input_path.is_dir():
        ms_dir = find_ms_directory(input_path)
        if ms_dir is not None:
            return ms_dir
    return None


def resolve_metadata_scraper(script_dir: Path) -> Path:
    candidates = [
        script_dir / "metadata-scraper-ASC.py",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "Could not find an ASC metadata scraper script. Expected one of: "
        + ", ".join(path.name for path in candidates)
    )


def scrape_local_metadata(input_path: Path, project_code: Optional[str] = None) -> dict:
    script_dir = Path(__file__).resolve().parent
    metadata_script = resolve_metadata_scraper(script_dir)
    command = [
        sys.executable,
        str(metadata_script),
        str(input_path),
        "--output-format",
        "json",
    ]
    if project_code:
        command.extend(["--project-code", project_code])

    result = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = result.communicate()
    stdout_text = stdout.decode("utf-8", errors="replace")
    stderr_text = stderr.decode("utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(stderr_text.strip() or f"{metadata_script.name} failed with code {result.returncode}")
    try:
        return json.loads(stdout_text)
    except ValueError as exc:
        raise RuntimeError(f"Could not parse {metadata_script.name} output: {exc}\nOutput:\n{stdout_text}") from exc


def resolve_metadata_from_source(
    source_path: Optional[Union[str, Path]],
    project_code: Optional[str] = None,
    object_name: Optional[str] = None,
    observation_date: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    if source_path is None:
        return project_code, object_name, observation_date

    source_path = Path(source_path).expanduser()
    if not source_path.exists():
        raise FileNotFoundError(f"Source path does not exist: {source_path}")

    metadata = scrape_local_metadata(source_path, project_code=project_code)
    resolved_project_code = metadata.get("project_code")
    if not resolved_project_code or resolved_project_code == "unknown":
        resolved_project_code = project_code

    resolved_object_name = metadata.get("object_name")
    if not resolved_object_name or resolved_object_name == "unknown":
        resolved_object_name = object_name

    resolved_observation_date = metadata.get("observation_date")
    if not resolved_observation_date or resolved_observation_date == "unknown":
        resolved_observation_date = observation_date

    return resolved_project_code, resolved_object_name, resolved_observation_date


def prepare_workdir_from_local_input(
    input_path: Path,
    workdir: Path,
    project_code: str,
    object_name: str,
    observation_date: str,
    asc_template: str,
) -> Path:
    workdir.mkdir(parents=True, exist_ok=False)
    ms_source = resolve_local_measurement_set(input_path)
    if ms_source is None:
        raise RuntimeError(
            f"Could not locate a measurement set under local path: {input_path}. "
            "Provide a path to a .ms directory or a directory containing an MS."
        )
    desired_ms_name = f"{project_code}.{object_name}.{observation_date}.ms"
    dest_ms_path = workdir / desired_ms_name
    if ms_source.resolve() != dest_ms_path.resolve():
        shutil.copytree(str(ms_source), str(dest_ms_path))
    template_src = Path(asc_template) if Path(asc_template).is_absolute() else (Path.cwd() / asc_template)
    if not template_src.exists():
        raise FileNotFoundError(f"ASC template directory does not exist: {template_src}")
    copy_tree(template_src, workdir)
    return dest_ms_path


def rename_workdir_and_measurement_set(
    original_workdir: Path,
    project_code: str,
    object_name: str,
    observation_date: str,
    old_ms_path: Path,
) -> Tuple[Path, Path]:
    measurement_set_name = f"{project_code}.{object_name}.{observation_date}.ms"
    new_workdir = compute_workdir(project_code, object_name, observation_date)
    old_ms_name = old_ms_path.name
    if new_workdir != original_workdir:
        if new_workdir.exists():
            raise FileExistsError(f"Destination workdir already exists: {new_workdir}")
        original_workdir.rename(new_workdir)
        old_ms_path = new_workdir / old_ms_name
    if old_ms_path.name != measurement_set_name:
        new_ms_path = new_workdir / measurement_set_name
        if new_ms_path.exists():
            raise FileExistsError(f"Target measurement set already exists: {new_ms_path}")
        old_ms_path.rename(new_ms_path)
        old_ms_path = new_ms_path
    return new_workdir, old_ms_path


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

    if "A_config" not in found_keys:
        insert_idx = 0
        for idx, line in enumerate(updated_lines):
            if line.startswith("#") or line.strip() == "":
                continue
            insert_idx = idx
            break
        updated_lines.insert(insert_idx, f'A_config = {str(a_config)}  # Set to True to use special resources for L band')

    if "measurement_set" not in found_keys:
        raise RuntimeError("Could not find measurement_set assignment in prep script")

    prep_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")


def write_casa_wrapper_script(workdir: Path, prep_script_path: str) -> Path:
    wrapper_path = workdir / "__run_prep_with_pandas.py"
    wrapper_path.write_text(
        """
import os
import sys

sys.path.insert(0, os.getcwd())

try:
    import pandas as pd
except Exception:
    import install_pandas
    import pandas as pd

print(f'Running prep script with pandas {pd.__version__}')

exec(open('prep-ms-for-auto-selfcal.py').read(), globals())
""",
        encoding="utf-8",
    )
    return wrapper_path


def launch_casa_and_exec_prep(casa_executable: str, workdir: Path, prep_script_path: str, skip_submit: bool) -> None:
    wrapper_script = write_casa_wrapper_script(workdir, prep_script_path)
    command = [
        casa_executable,
        "--nogui",
        "-c",
        f"exec(open('{wrapper_script.name}').read())",
    ]
    print(f"Launching CASA non-interactively: {' '.join(command)}")
    subprocess.run(command, cwd=workdir, check=True)

    if skip_submit:
        print("Skipping submit batch execution as requested.")
        return

    submit_script = workdir / "submit_batch_of_batch_jobs.py"
    if not submit_script.exists():
        raise FileNotFoundError(f"Submit script not found at {submit_script}")

    print(f"Submitting batch jobs using {submit_script}")
    subprocess.run([sys.executable, submit_script.name], cwd=workdir, check=True)

def main():
    args = parse_args()

    named_inputs, positional_inputs = parse_named_inputs(sys.argv[1:])
    if named_inputs.get("project_code") and not args.project_code:
        args.project_code = named_inputs["project_code"]
    if named_inputs.get("object_name") and not args.object_name:
        args.object_name = named_inputs["object_name"]
    if named_inputs.get("observation_date") and not args.observation_date:
        args.observation_date = named_inputs["observation_date"]
    if named_inputs.get("url") and not args.url:
        args.url = named_inputs["url"]
    if named_inputs.get("source") and not args.ms_path and not args.source:
        args.source = named_inputs["source"]

    if args.project_code and args.project_code.startswith("url="):
        args.url = args.project_code.split("=", 1)[1]
        args.project_code = None

    if not args.url and args.object_name and args.object_name.startswith("url="):
        args.url = args.object_name.split("=", 1)[1]
        args.object_name = None

    if not args.url and args.observation_date and args.observation_date.startswith("url="):
        args.url = args.observation_date.split("=", 1)[1]
        args.observation_date = None

    if not args.url and args.url_arg:
        if args.url_arg.startswith("url="):
            args.url = args.url_arg.split("=", 1)[1]
        else:
            args.url = args.url_arg

    source_value = args.ms_path or args.source
    if source_value:
        source_path = Path(source_value).expanduser()
        if not source_path.exists():
            sys.exit(f"Error: source path does not exist: {source_path}")
        if args.url:
            print("Warning: source path provided; ignoring --url and using local input instead.")

        try:
            args.project_code, args.object_name, args.observation_date = resolve_metadata_from_source(
                source_path,
                project_code=args.project_code,
                object_name=args.object_name,
                observation_date=args.observation_date,
            )
        except RuntimeError as exc:
            sys.exit(f"Error extracting metadata from local input: {exc}")

    if args.ms_path:
        ms_input = Path(args.ms_path)
        metadata_missing = [
            name
            for name, value in [
                ("project_code", args.project_code),
                ("object_name", args.object_name),
                ("observation_date", args.observation_date),
            ]
            if not value
        ]
        if metadata_missing:
            sys.exit(
                "Missing metadata: {}. Provide these manually or supply an input path with enough metadata."
                .format(", ".join(metadata_missing))
            )

        build_project_code = args.project_code
        build_object = args.object_name
        build_date = args.observation_date
        script_dir = Path(__file__).resolve().parent
        workdir = compute_workdir(build_project_code, build_object, build_date)

        if args.dry_run:
            print(f"Dry run enabled. Would create workdir from local input: {ms_input}")
            print(f"Workdir would be: {workdir}")
            return

        try:
            ms_path = prepare_workdir_from_local_input(
                ms_input,
                workdir,
                build_project_code,
                build_object,
                build_date,
                args.asc,
            )
        except Exception as exc:
            sys.exit(f"Error preparing workdir from local input: {exc}")

        source_name = args.source_name or build_object
        prep_script_path = workdir / "prep-ms-for-auto-selfcal.py"
        print(f"Patching prep script at {prep_script_path}")
        patch_prep_script(
            prep_script_path,
            measurement_set=ms_path.name,
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

        if args.run_casa:
            print("Launching CASA non-interactively in the workdir and executing the prep script...")
            launch_casa_and_exec_prep(
                args.casa_executable,
                workdir,
                prep_script_path.name,
                args.skip_submit,
            )
        else:
            print("To run CASA manually instead, execute:")
            print(f"  cd {workdir}")
            print(f"  {args.casa_executable} --nogui -c \"exec(open('{prep_script_path.name}').read())\"")
        return

    if not args.url:
        sys.exit(
            "Usage error: url must be provided either with --url or as a positional argument like url=<value> or <raw-url>."
        )

    # Try to extract project code from URL path before building
    url_project_code = extract_project_code_from_url(args.url)
    if url_project_code and (not args.project_code or args.project_code == "unknown"):
        print(f"Extracted project code from URL path: {url_project_code}")
        args.project_code = url_project_code

    build_project_code = args.project_code or "unknown"
    build_object = args.object_name or "unknown"
    build_date = args.observation_date or "unknown"
    script_dir = Path(__file__).resolve().parent
    workdir = compute_workdir(build_project_code, build_object, build_date)
    source_name = args.source_name or build_object

    build_cmd = [
        sys.executable,
        str(script_dir / "build_ASC.py"),
        build_project_code,
        build_object,
        args.url,
        build_date,
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

    ms_path = find_ms_directory(workdir)
    if ms_path is None:
        sys.exit(f"Error: No .ms directory found in workdir {workdir}")

    extracted_metadata_file = workdir / ".extracted_metadata"
    if extracted_metadata_file.exists():
        print(f"Reading extracted metadata from {extracted_metadata_file}")
        args.project_code, args.object_name, args.observation_date = apply_extracted_metadata(
            workdir,
            project_code=args.project_code,
            object_name=args.object_name,
            observation_date=args.observation_date,
        )
    else:
        print(f"Note: No extracted metadata file found at {extracted_metadata_file}")

    metadata_missing = [
        name
        for name, value in [
            ("project_code", args.project_code),
            ("object_name", args.object_name),
            ("observation_date", args.observation_date),
        ]
        if not value or value == "unknown"
    ]
    if args.use_ms_metadata or metadata_missing:
        ms_command = [
            sys.executable,
            str(resolve_metadata_scraper(script_dir)),
            str(ms_path),
            "--output-format",
            "json",
        ]
        if args.project_code and args.project_code != "unknown":
            ms_command.extend(["--project-code", args.project_code])
        
        print(f"Inferring ASC metadata from {resolve_metadata_scraper(script_dir).name}:")
        print(" ".join(ms_command))
        
        result = subprocess.run(
            ms_command,
            cwd=script_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            check=False,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            sys.exit(f"Error extracting metadata from MS path: {stderr or f'Metadata scraper failed with code {result.returncode}'}")
        try:
            ms_metadata = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            sys.exit(f"Error parsing metadata from {resolve_metadata_scraper(script_dir).name}: {exc}\nOutput:\n{result.stdout}")
        if not args.project_code or args.project_code == "unknown":
            args.project_code = ms_metadata["project_code"]
        if not args.object_name or args.object_name == "unknown":
            args.object_name = ms_metadata["object_name"]
        if not args.observation_date or args.observation_date == "unknown":
            args.observation_date = ms_metadata["observation_date"]
        metadata_missing = [
            name
            for name, value in [
                ("project_code", args.project_code),
                ("object_name", args.object_name),
                ("observation_date", args.observation_date),
            ]
            if not value or value == "unknown"
        ]

        if not metadata_missing:
            workdir, ms_path = rename_workdir_and_measurement_set(
                workdir,
                args.project_code,
                args.object_name,
                args.observation_date,
                ms_path,
            )

    if metadata_missing:
        sys.exit(
            f"Could not resolve {', '.join(metadata_missing)}. "
            "Provide them explicitly or ensure the metadata scraper can extract them from the measurement set."
        )

    # Convert "unknown" to None for cleaner handling
    if args.project_code == "unknown":
        args.project_code = None
    if args.object_name == "unknown":
        args.object_name = None
    if args.observation_date == "unknown":
        args.observation_date = None

    # Final validation
    if not args.project_code or not args.object_name or not args.observation_date:
        sys.exit(
            f"Could not resolve all required metadata. "
            f"project_code={args.project_code}, object_name={args.object_name}, observation_date={args.observation_date}. "
            "Provide them explicitly or ensure the metadata scraper can extract them from the measurement set."
        )

    print(
        f"Resolved ASC metadata: project_code={args.project_code}, object_name={args.object_name}, "
        f"observation_date={args.observation_date}"
    )

    if args.object_name and args.observation_date:
        measurement_set_name = f"{args.project_code}.{args.object_name}.{args.observation_date}.ms"
        if ms_path.name != measurement_set_name:
            ms_path = ms_path.rename(workdir / measurement_set_name)

    source_name = args.source_name or args.object_name
    measurement_set_name = f"{args.project_code}.{args.object_name}.{args.observation_date}.ms"
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

    if args.run_casa:
        print("Launching CASA non-interactively in the workdir and executing the prep script...")
        launch_casa_and_exec_prep(
            args.casa_executable,
            workdir,
            prep_script_path.name,
            args.skip_submit,
        )
    else:
        print("To run CASA manually instead, execute:")
        print(f"  cd {workdir}")
        print(f"  {args.casa_executable} --nogui -c \"exec(open('{prep_script_path.name}').read())\"")


if __name__ == "__main__":
    main()
