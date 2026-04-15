import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

try:
    from astropy.time import Time
except ImportError:
    Time = None


def parse_args():
    parser = argparse.ArgumentParser(
        description="Extract project, object, and observation date metadata from a measurement set and optionally rename it."
    )
    parser.add_argument("mspath", help="Path to the measurement set directory")
    parser.add_argument("--field", type=int, default=2, help="Field index to use for the target name")
    parser.add_argument("--project-code", default=None, help="Project code override to use if not inferable from the MS path")
    parser.add_argument("--rename", action="store_true", help="Rename the MS into the cleaned directory/name layout")
    parser.add_argument(
        "--output-format",
        choices=["plain", "json"],
        default="plain",
        help="Output format for the extracted metadata",
    )
    return parser.parse_args()


def parse_renamed_mspath(ms_path):
    parts = Path(ms_path).stem.split('.')
    if len(parts) >= 3 and re.match(r"^\d{4}-\d{2}-\d{2}$", parts[2]):
        return parts[0], parts[1], parts[2]
    return None


def normalize_date_token(token):
    if re.match(r"^\d{4}-\d{2}-\d{2}$", token):
        return token
    m = re.match(r"^(\d{4})(\d{2})(\d{2})$", token)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r"^(\d{4})(\d{2})(\d{2})[-_].*$", token)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


def infer_metadata_from_path(ms_path, project_code_override=None):
    project_code = project_code_override
    segments = [Path(seg).name for seg in (Path(ms_path).parents)] + [Path(ms_path).name]

    if project_code is None:
        for segment in segments:
            if re.match(r'^[0-9]{2}[A-Z]-[0-9]{3}$', segment):
                project_code = segment
                break

    date_candidate = None
    target_candidate = None

    for segment in segments:
        parts = segment.split('.')
        if len(parts) >= 3:
            maybe_date = normalize_date_token(parts[-1])
            if maybe_date:
                date_candidate = maybe_date
                if project_code is None and re.match(r'^[0-9]{2}[A-Z]-[0-9]{3}$', parts[0]):
                    project_code = parts[0]
                if len(parts) >= 3:
                    target_candidate = '.'.join(parts[1:-1])
                break

    if date_candidate is None:
        for segment in segments:
            maybe_date = normalize_date_token(segment)
            if maybe_date:
                date_candidate = maybe_date
                break

    if target_candidate is None and project_code and date_candidate:
        for segment in segments:
            if project_code in segment and date_candidate.replace('-', '') in segment:
                parts = segment.split('.')
                if len(parts) >= 3:
                    target_candidate = '.'.join(parts[1:-1])
                    break

    if target_candidate is None:
        parent_name = Path(ms_path).parent.name
        if parent_name and parent_name != project_code and normalize_date_token(parent_name) is None:
            target_candidate = parent_name

    if date_candidate is None:
        for segment in segments:
            if "date" in segment.lower():
                maybe_date = normalize_date_token(segment)
                if maybe_date:
                    date_candidate = maybe_date
                    break

    return project_code, target_candidate, date_candidate


def format_date_from_mjd(mjd_value):
    if Time is None:
        raise RuntimeError("astropy is required to convert MJD timestamps. Install astropy and retry.")
    return Time(mjd_value, format="mjd").strftime("%Y-%m-%d")


def extract_from_casacore(ms_path, field_index):
    try:
        from casacore.tables import table
    except ImportError:
        return None

    ms_dir = str(ms_path)
    try:
        field_table = table(ms_dir + "/FIELD")
        field_names = field_table.getcol("NAME")
        if len(field_names) == 0:
            field_table.close()
            return None
        target = field_names[field_index] if field_index < len(field_names) else field_names[0]
        field_table.close()

        obs_table = table(ms_dir + "/OBSERVATION")
        if "DATE_OBS" in obs_table.colnames():
            date_obs = obs_table.getcell("DATE_OBS", 0)
        elif "TIME_RANGE" in obs_table.colnames():
            time_range = obs_table.getcell("TIME_RANGE", 0)
            date_obs = time_range[0] if len(time_range) >= 1 else None
        else:
            date_obs = None
        obs_table.close()

        if date_obs is None:
            return None

        if isinstance(date_obs, str):
            return target, date_obs.split("T")[0]

        if Time is None:
            raise RuntimeError("astropy is required to convert numeric time values from casacore.")

        return target, format_date_from_mjd(date_obs)
    except Exception:
        return None


def extract_ms_metadata(ms_path, field_index=2, project_code_override=None):
    ms_path = Path(ms_path)
    if not ms_path.exists():
        raise FileNotFoundError(f"Measurement set path not found: {ms_path}")

    renamed = parse_renamed_mspath(ms_path)
    if renamed:
        project_code, target, obs_date = renamed
        return project_code, target, obs_date

    project_code = project_code_override

    result = extract_from_casacore(ms_path, field_index)
    if result is not None:
        target, obs_date = result
        if project_code is None:
            project_code = infer_metadata_from_path(ms_path, project_code_override)[0]
        if project_code is None:
            raise RuntimeError(
                "Project code could not be inferred from the MS path. "
                "Provide --project-code or use a renamed MS path."
            )
        return project_code, target, obs_date

    path_project, path_target, path_date = infer_metadata_from_path(ms_path, project_code_override)
    if path_project and path_target and path_date:
        return path_project, path_target, path_date

    raise RuntimeError(
        "Could not extract target and observation date from the measurement set. "
        "Install casacore/astropy or provide an MS path already renamed in the expected form."
    )


def build_new_mspath(ms_path, project_code, target, obs_date):
    ms_path = Path(ms_path)
    parent_dir = ms_path.parent
    return parent_dir / f"{project_code}.{target}.{obs_date}.ms"


def rename_ms(ms_path, new_mspath):
    if new_mspath.exists():
        raise FileExistsError(f"Target path already exists: {new_mspath}")
    shutil.move(str(ms_path), str(new_mspath))
    return new_mspath


def main():
    args = parse_args()
    project_code, target, obs_date = extract_ms_metadata(
        args.mspath,
        field_index=args.field,
        project_code_override=args.project_code,
    )
    output = {
        "project_code": project_code,
        "object_name": target,
        "observation_date": obs_date,
    }

    if args.rename:
        new_mspath = build_new_mspath(args.mspath, project_code, target, obs_date)
        rename_ms(args.mspath, new_mspath)
        output["renamed_path"] = str(new_mspath)

    if args.output_format == "json":
        print(json.dumps(output))
    else:
        print(project_code)
        print(target)
        print(obs_date)
        if args.rename:
            print(str(output["renamed_path"]))


if __name__ == "__main__":
    main()
