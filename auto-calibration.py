#!/usr/bin/env python3

import argparse
from collections import deque
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional, Tuple


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Run CB, ASC, or CB->ASC calibration workflows from one entrypoint."
        )
    )
    parser.add_argument("project_code", nargs="?", help="Project code, e.g. 23A-241")
    parser.add_argument("object_name", nargs="?", help="Object name, e.g. AT2019ehz")
    parser.add_argument(
        "observation_date_pos",
        nargs="?",
        help="Optional positional observation date for backward-compatible invocation forms",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose output and command tracing")
    parser.add_argument("-q", "--quiet", action="store_true", help="Reduce output to essential status/error messages")
    parser.add_argument(
        "--pipeline",
        default="cb-asc",
        choices=["cb", "asc", "cb-asc", "auto-image"],
        help="Pipeline mode: cb, asc, cb-asc, or auto-image (default: cb-asc)",
    )
    parser.add_argument("--observation-date", help="Observation date, e.g. 2023-07-22")
    parser.add_argument("--url", help="Source URL/path; pipeline-specific behavior is inferred from --pipeline")
    parser.add_argument("--cb-workdir", help="Existing CB working directory to use instead of running build/prep")
    parser.add_argument(
        "--asc-ms-path",
        help="Path to a local .ms directory or parent directory containing one for ASC-only mode",
    )
    parser.add_argument("--skip-cb", action="store_true", help="Skip CB build/prep and use --cb-workdir directly")
    parser.add_argument("--cb-template", default="CB", help="Path to the CB template directory")
    parser.add_argument(
        "--cb-auto-image-vla",
        default="repo/auto-image-VLA",
        help="Path to auto-image-VLA directory copied into CB working directories",
    )
    parser.add_argument("--asc-template", default="ASC", help="Path to the ASC template directory")
    parser.add_argument("--cb-temp-dir", help="Optional temporary directory for CB downloads and extraction")

    parser.add_argument(
        "--cb-submit",
        action="store_true",
        help="Submit CB batch jobs after build/prep. By default the wrapper skips CB submission.",
    )
    parser.add_argument(
        "--cb-wait-seconds",
        type=int,
        default=60,
        help="Polling interval in seconds when waiting for CB SLURM completion (default: 60).",
    )

    parser.add_argument(
        "--auto-image-workdir",
        help="Existing working directory containing auto-image-VLA and config.yaml for standalone auto-image mode.",
    )
    parser.add_argument(
        "--auto-image-submit",
        action="store_true",
        help="Submit auto-image via sbatch run_auto_image.sh instead of running CASA directly.",
    )
    parser.add_argument(
        "--auto-image-casa-executable",
        default="casa-pipe",
        help="CASA executable to use for standalone auto-image direct runs.",
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


def normalize_cli_inputs(args: argparse.Namespace) -> argparse.Namespace:
    named_inputs, _ = parse_named_inputs(sys.argv[1:])

    if args.observation_date_pos and not args.observation_date:
        args.observation_date = args.observation_date_pos

    if named_inputs.get("project_code"):
        args.project_code = named_inputs["project_code"]
    if named_inputs.get("object_name"):
        args.object_name = named_inputs["object_name"]
    if named_inputs.get("observation_date"):
        args.observation_date = named_inputs["observation_date"]
    if named_inputs.get("url"):
        args.url = named_inputs["url"]

    # Accept split form: "url= https://..."
    if not args.url:
        saw_url_marker = False
        for token in sys.argv[1:]:
            if token.lower() == "url=":
                saw_url_marker = True
                continue
            if saw_url_marker:
                args.url = token
                break

    return args


def compute_cb_workdir(project_code: str, object_name: str, observation_date: str) -> Path:
    return Path(f"working.{project_code}.{object_name}.{observation_date}")


def parse_directory_links(html: str):
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


def fetch_directory_links(url: str):
    with urllib.request.urlopen(url) as response:
        html = response.read().decode("utf-8", errors="ignore")
    return parse_directory_links(html)


def is_remote_url(value: str) -> bool:
    text = (value or "").strip().lower()
    return text.startswith("http://") or text.startswith("https://")


def probe_remote_url_type(url: str, max_depth: int = 8, max_dirs: int = 600) -> str:
    queue = deque([(url.rstrip("/"), 0)])
    visited = set()
    saw_cb_hint = False
    saw_asc_hint = False

    while queue and len(visited) < max_dirs:
        current_url, depth = queue.popleft()
        if current_url in visited:
            continue
        visited.add(current_url)

        tail = current_url.rstrip("/").split("/")[-1].lower()
        if tail.startswith("observation"):
            saw_cb_hint = True
        if tail.endswith(".ms"):
            saw_asc_hint = True

        try:
            links = fetch_directory_links(current_url)
        except Exception:
            continue

        for link in links:
            link_clean = link.rstrip("/")
            lower = link_clean.lower()
            is_dir = link.endswith("/")

            if is_dir and lower.startswith("observation"):
                saw_cb_hint = True
            if is_dir and lower.endswith(".ms"):
                saw_asc_hint = True

            if depth < max_depth and is_dir:
                next_url = current_url.rstrip("/") + "/" + link.lstrip("/")
                queue.append((next_url.rstrip("/"), depth + 1))

        if saw_cb_hint and saw_asc_hint:
            return "mixed"

    if saw_cb_hint:
        return "cb"
    if saw_asc_hint:
        return "asc"
    return "unknown"


def resolve_source_url(args: argparse.Namespace) -> Optional[str]:
    return args.url


def validate_url_for_pipeline(url: Optional[str], pipeline: str, quiet: bool = False) -> None:
    if not url or not is_remote_url(url):
        return

    url_type = probe_remote_url_type(url)
    if not quiet:
        print(f"URL probe result: {url_type}")

    if pipeline in {"cb", "cb-asc"} and url_type == "asc":
        sys.exit(
            "Error: The provided URL looks like an ASC-style source (contains .ms directories), "
            "but CB/CB-ASC mode expects a CB archive/tree source (observation directories)."
        )

    if pipeline == "asc" and url_type == "cb":
        sys.exit(
            "Error: The provided URL looks like a CB-style source (observation directories), "
            "but ASC mode expects an ASC-style source with .ms content."
        )


def is_ms_dir(path: Path) -> bool:
    if not path.is_dir():
        return False
    if path.suffix == ".ms":
        return True
    folder_names = {child.name.upper() for child in path.iterdir() if child.is_dir()}
    return bool(folder_names & {"FIELD", "MAIN", "ANTENNA", "SOURCE", "SPECTRAL_WINDOW", "OBSERVATION"})


def find_ms_directory(root_dir: Path) -> Optional[Path]:
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


def run_subprocess(command, cwd: Path, quiet: bool = False, verbose: bool = False) -> subprocess.CompletedProcess:
    if verbose and not quiet:
        print("Running:")
        print(" ".join(str(arg) for arg in command), flush=True)

    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")

    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        bufsize=1,
        env=env,
    )

    output_chunks = []
    assert process.stdout is not None
    for line in process.stdout:
        output_chunks.append(line)
        if not quiet:
            print(line, end="", flush=True)

    return_code = process.wait()
    combined_output = "".join(output_chunks)
    result = subprocess.CompletedProcess(
        args=command,
        returncode=return_code,
        stdout=combined_output,
        stderr="",
    )
    if return_code != 0:
        if quiet and combined_output:
            print(combined_output, file=sys.stderr, end="" if combined_output.endswith("\n") else "\n")
        raise subprocess.CalledProcessError(return_code, command, output=combined_output, stderr="")
    return result


def extract_submitted_job_ids(text: str):
    return re.findall(r"Submitted\s+batch\s+job\s+(\d+)", text or "")


def parse_state_token(state_value: str) -> str:
    cleaned = (state_value or "").strip().upper()
    if not cleaned:
        return ""
    # Slurm may report forms like COMPLETED+, FAILED (exit code ...), etc.
    cleaned = cleaned.split()[0]
    cleaned = cleaned.split("+")[0]
    return cleaned


def get_slurm_job_state(job_id: str) -> str:
    sacct_cmd = ["sacct", "-j", str(job_id), "--format=State", "--noheader", "--parsable2"]
    try:
        sacct_result = subprocess.run(
            sacct_cmd,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
    except OSError:
        sacct_result = None

    if sacct_result and sacct_result.returncode == 0:
        states = []
        for line in sacct_result.stdout.splitlines():
            token = parse_state_token(line.split("|", 1)[0] if "|" in line else line)
            if token:
                states.append(token)
        failure_states = {
            "FAILED",
            "CANCELLED",
            "TIMEOUT",
            "OUT_OF_MEMORY",
            "NODE_FAIL",
            "PREEMPTED",
            "BOOT_FAIL",
            "DEADLINE",
        }
        active_states = {
            "PENDING",
            "RUNNING",
            "CONFIGURING",
            "COMPLETING",
            "RESIZING",
            "SUSPENDED",
            "SIGNALING",
            "STAGE_OUT",
            "REQUEUED",
            "REQUEUE_FED",
        }

        # sacct can include multiple entries for one job id (job, batch, extern).
        # Never treat the job as complete while any active state is still present.
        for candidate in failure_states:
            if candidate in states:
                return candidate
        for candidate in active_states:
            if candidate in states:
                return candidate
        if "COMPLETED" in states:
            return "COMPLETED"
        if states:
            return states[-1]

    squeue_cmd = ["squeue", "-j", str(job_id), "-h", "-o", "%T"]
    try:
        squeue_result = subprocess.run(
            squeue_cmd,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
    except OSError:
        return "UNKNOWN"

    if squeue_result.returncode == 0:
        state_text = squeue_result.stdout.strip()
        if state_text:
            return parse_state_token(state_text.splitlines()[0])
        return "PENDING_ACCOUNTING"

    return "UNKNOWN"


def wait_for_slurm_job_completion(job_id: str, poll_seconds: int, quiet: bool = False) -> None:
    success_states = {"COMPLETED"}
    failure_states = {"FAILED", "CANCELLED", "TIMEOUT", "OUT_OF_MEMORY", "NODE_FAIL", "PREEMPTED"}

    interval = max(5, int(poll_seconds))
    if not quiet:
        print(f"Waiting for CB SLURM job {job_id} to complete before launching ASC...")
    while True:
        state = get_slurm_job_state(job_id)
        if not quiet:
            print(f"CB job {job_id} state: {state}")
        if state in success_states:
            print(f"CB SLURM job {job_id} completed successfully.")
            return
        if state in failure_states:
            sys.exit(f"Error: CB SLURM job {job_id} ended with state {state}; ASC will not start.")
        time.sleep(interval)


def run_auto_image_workflow(args: argparse.Namespace) -> None:
    script_dir = Path(__file__).resolve().parent
    workdir_input = args.auto_image_workdir or args.cb_workdir
    if not workdir_input:
        sys.exit("Error: auto-image mode requires --auto-image-workdir (or --cb-workdir).")

    workdir = Path(workdir_input).expanduser()
    if not workdir.is_absolute():
        workdir = script_dir / workdir
    workdir = workdir.resolve()

    if not workdir.exists() or not workdir.is_dir():
        sys.exit(f"Error: auto-image workdir not found: {workdir}")

    auto_image_dir = workdir / "auto-image-VLA"
    config_path = auto_image_dir / "config.yaml"
    auto_image_script = auto_image_dir / "run-auto-image.py"

    if args.auto_image_submit:
        submit_script = workdir / "run_auto_image.sh"
        if not submit_script.exists():
            sys.exit(
                f"Error: expected auto-image submit script not found: {submit_script}. "
                "Generate it via CB prep first, or run direct mode without --auto-image-submit."
            )

        cmd = ["sbatch", str(submit_script)]
        if args.dry_run:
            print("Auto-image dry run enabled; the following command would be executed:")
            print(" ".join(cmd))
            return

        run_subprocess(cmd, cwd=workdir, quiet=args.quiet, verbose=args.verbose)
        print("Standalone auto-image sbatch submission completed.")
        return

    if not auto_image_script.exists():
        sys.exit(f"Error: auto-image script not found: {auto_image_script}")
    if not config_path.exists():
        sys.exit(f"Error: auto-image config not found: {config_path}")

    casa_executable = args.auto_image_casa_executable
    commands = []
    install_code = (
        "import subprocess,sys;"
        "print(f'Installing pandas into CASA Python: {sys.executable}');"
        "subprocess.run([sys.executable,'-m','pip','install','--user','pandas'],check=True)"
    )
    commands.append([casa_executable, "--nogui", "-c", install_code])

    run_code = (
        "import os,sys;"
        "_user_site=os.path.expanduser(f'~/.local/lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages');"
        "sys.path.insert(0,_user_site) if _user_site not in sys.path else None;"
        "from casatasks import listobs,tclean,imfit,imstat,imhead;"
        "import runpy;runpy.run_path('run-auto-image.py', init_globals=globals(), run_name='__main__')"
    )
    commands.append([casa_executable, "--nogui", "-c", run_code])

    if args.dry_run:
        print("Auto-image dry run enabled; the following command(s) would be executed:")
        for command in commands:
            print(" ".join(str(arg) for arg in command))
        return

    for command in commands:
        run_subprocess(command, cwd=auto_image_dir, quiet=args.quiet, verbose=args.verbose)

    print("Standalone auto-image direct run completed.")


def list_cb_workdirs(script_dir: Path):
    return {p.resolve() for p in script_dir.glob("working.*") if p.is_dir()}


def run_cb_workflow(args: argparse.Namespace) -> Tuple[Path, Optional[str]]:
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

        print(f"Skipping CB build/prep and using existing workdir: {cb_workdir}")
        return cb_workdir, None

    cb_url = resolve_source_url(args)
    if not cb_url:
        sys.exit("Error: a source URL/path is required for CB mode (use --url).")

    cb_workdir = None
    if args.project_code and args.object_name and args.observation_date:
        cb_workdir = compute_cb_workdir(args.project_code, args.object_name, args.observation_date)

    cmd = [sys.executable, str(cb_script)]
    if args.project_code:
        cmd.append(f"project_code={args.project_code}")
    if args.object_name:
        cmd.append(f"object_name={args.object_name}")
    if args.observation_date:
        cmd.append(f"observation_date={args.observation_date}")
    cmd.extend(["--url", cb_url])
    cmd.extend(["--cb", args.cb_template])
    cmd.extend(["--auto-image-vla", args.cb_auto_image_vla])
    if args.verbose:
        cmd.append("--verbose")
    if args.quiet:
        cmd.append("--quiet")
    if args.cb_temp_dir:
        cmd.extend(["--temp-dir", args.cb_temp_dir])
    if not args.cb_submit:
        cmd.append("--skip-submit")
    if args.dry_run:
        cmd.append("--dry-run")

    if args.dry_run:
        print("CB dry run enabled; the following command would be executed:")
        print(" ".join(str(arg) for arg in cmd))
        return (cb_workdir if cb_workdir is not None else Path("working.unknown.unknown.unknown"), None)

    before_workdirs = list_cb_workdirs(script_dir)
    result = run_subprocess(cmd, cwd=script_dir, quiet=args.quiet, verbose=args.verbose)
    after_workdirs = list_cb_workdirs(script_dir)
    submitted_job_ids = extract_submitted_job_ids((result.stdout or "") + "\n" + (result.stderr or ""))
    final_job_id = submitted_job_ids[-1] if submitted_job_ids else None

    if cb_workdir is not None and cb_workdir.exists():
        return cb_workdir, final_job_id

    created = sorted(after_workdirs - before_workdirs)
    if len(created) == 1:
        return created[0], final_job_id
    if len(created) > 1:
        # Prefer the most recently modified workdir when multiple are created.
        return max(created, key=lambda p: p.stat().st_mtime), final_job_id

    raise FileNotFoundError("Could not determine CB workdir after build. Provide metadata explicitly or use --cb-workdir.")


def run_asc_workflow(args: argparse.Namespace, ms_path: Path) -> None:
    script_dir = Path(__file__).resolve().parent
    asc_script = script_dir / "run_build_and_prep_ASC.py"
    if not asc_script.exists():
        raise FileNotFoundError(f"Could not find ASC wrapper script: {asc_script}")

    cmd = [sys.executable, str(asc_script)]
    if args.project_code:
        cmd.append(f"project_code={args.project_code}")
    if args.object_name:
        cmd.append(f"object_name={args.object_name}")
    if args.observation_date:
        cmd.append(f"observation_date={args.observation_date}")
    cmd.extend(["--ms-path", str(ms_path)])
    cmd.extend(["--asc", args.asc_template])
    if args.verbose:
        cmd.append("--verbose")
    if args.quiet:
        cmd.append("--quiet")
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
        cmd.append("--no-run-casa")
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

    run_subprocess(cmd, cwd=script_dir, quiet=args.quiet, verbose=args.verbose)


def run_asc_remote_workflow(args: argparse.Namespace, source_url: str) -> None:
    script_dir = Path(__file__).resolve().parent
    asc_script = script_dir / "run_build_and_prep_ASC.py"
    if not asc_script.exists():
        raise FileNotFoundError(f"Could not find ASC wrapper script: {asc_script}")

    cmd = [sys.executable, str(asc_script)]
    if args.project_code:
        cmd.append(f"project_code={args.project_code}")
    if args.object_name:
        cmd.append(f"object_name={args.object_name}")
    if args.observation_date:
        cmd.append(f"observation_date={args.observation_date}")
    cmd.extend(["--url", source_url])
    cmd.extend(["--asc", args.asc_template])
    if args.verbose:
        cmd.append("--verbose")
    if args.quiet:
        cmd.append("--quiet")
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
        cmd.append("--no-run-casa")
    if args.asc_skip_submit:
        cmd.append("--skip-submit")
    if args.asc_dry_run or args.dry_run:
        cmd.append("--dry-run")
    if args.asc_casa_executable != "casa":
        cmd.extend(["--casa-executable", args.asc_casa_executable])

    if args.dry_run:
        print("ASC remote dry run enabled; the following command would be executed:")
        print(" ".join(str(arg) for arg in cmd))
        return

    run_subprocess(cmd, cwd=script_dir, quiet=args.quiet, verbose=args.verbose)


def main() -> None:
    args = normalize_cli_inputs(parse_args())
    pipeline = args.pipeline
    source_url = resolve_source_url(args)

    if args.quiet and args.verbose:
        sys.exit("Error: --quiet and --verbose cannot be used together.")

    if args.dry_run:
        args.asc_dry_run = True

    if args.skip_cb and not args.cb_workdir:
        sys.exit("Error: --skip-cb requires --cb-workdir.")

    if source_url and is_remote_url(source_url):
        validate_url_for_pipeline(source_url, pipeline, quiet=args.quiet)

    if pipeline == "cb":
        cb_workdir, cb_final_job_id = run_cb_workflow(args)

        if args.dry_run:
            print("CB dry-run complete.")
            return

        if args.cb_submit:
            print("CB submission includes auto-image chaining via Slurm dependency.")
            if cb_final_job_id:
                wait_for_slurm_job_completion(cb_final_job_id, args.cb_wait_seconds, quiet=args.quiet)
            else:
                sys.exit(
                    "Error: CB submission was requested but no SLURM job ID was detected from CB output."
                )
            print("CB pipeline and chained auto-image completed successfully.")
            return

        print("Running standalone auto-image after CB workflow completion.")
        args.auto_image_workdir = str(cb_workdir)
        args.auto_image_submit = False
        run_auto_image_workflow(args)
        print("CB pipeline completed successfully (including standalone auto-image).")
        return

    if pipeline == "auto-image":
        run_auto_image_workflow(args)
        return

    if pipeline == "asc":
        asc_source = Path(args.asc_ms_path).expanduser() if args.asc_ms_path else None
        if asc_source is None and args.cb_workdir:
            asc_source = Path(args.cb_workdir).expanduser()
        if asc_source is None and source_url:
            run_asc_remote_workflow(args, source_url)
            print("ASC pipeline completed successfully.")
            return
        if asc_source is None:
            sys.exit("Error: ASC mode requires --asc-ms-path, --cb-workdir, or --url.")

        ms_path = find_ms_directory(asc_source)
        if ms_path is None:
            sys.exit(f"Error: Could not locate a .ms measurement set under {asc_source}.")

        print(f"Found ASC input measurement set: {ms_path}")
        run_asc_workflow(args, ms_path)
        print("ASC pipeline completed successfully.")
        return

    if pipeline == "cb-asc":
        if not args.cb_submit and not args.skip_cb:
            print("CB-ASC mode requires CB submission; enabling --cb-submit automatically.")
            args.cb_submit = True

    cb_workdir, cb_final_job_id = run_cb_workflow(args)

    if args.dry_run:
        print("Dry-run complete. No ASC workflow was executed because the wrapper is in dry-run mode.")
        return

    if args.cb_submit:
        if cb_final_job_id:
            wait_for_slurm_job_completion(cb_final_job_id, args.cb_wait_seconds, quiet=args.quiet)
        else:
            sys.exit(
                "Error: CB submission was requested but no SLURM job ID was detected from CB output. "
                "Inspect CB submit output and Slurm status."
            )

    ms_path = find_ms_directory(cb_workdir)
    if ms_path is None:
        sys.exit(f"Error: Could not locate a .ms measurement set inside the CB workdir {cb_workdir}.")

    print(f"Found CB measurement set for ASC input: {ms_path}")
    run_asc_workflow(args, ms_path)
    print("Combined CB->ASC auto-calibration workflow completed successfully.")


if __name__ == "__main__":
    main()
