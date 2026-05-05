import argparse
import json
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path
import xml.etree.ElementTree as ET


def parse_args():
    parser = argparse.ArgumentParser(
        description="Extract project code, object name, and observation date from either a CASA MS or an extracted SDM-BDF."
    )
    parser.add_argument("mspath", help="Path to the measurement set directory or extracted SDM-BDF root")
    parser.add_argument("--field", type=int, default=2, help="Field index to use for the target name when reading an MS")
    parser.add_argument("--project-code", default=None, help="Project code override when it cannot be inferred from the input data")
    parser.add_argument("--rename", action="store_true", help="Rename the MS into the cleaned directory/name layout")
    parser.add_argument(
        "--output-format",
        choices=["plain", "json"],
        default="plain",
        help="Output format for the extracted metadata",
    )
    return parser.parse_args()


def is_ms_dir(path):
    path = Path(path)
    if not path.is_dir():
        return False
    if path.suffix == ".ms":
        return True
    folder_names = {child.name.upper() for child in path.iterdir() if child.is_dir()}
    return bool(folder_names & {"FIELD", "MAIN", "ANTENNA", "SOURCE", "SPECTRAL_WINDOW", "OBSERVATION"})


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
    segments = [Path(seg).name for seg in Path(ms_path).parents] + [Path(ms_path).name]

    if project_code is None:
        for segment in segments:
            match = re.search(r"[0-9]{2}[A-Z]-[0-9]{3}", segment)
            if match:
                project_code = match.group(0)
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


def extract_ms_metadata(ms_path, field_index=2, project_code_override=None):
    ms_path = Path(ms_path)
    if not ms_path.exists():
        raise FileNotFoundError(f"Measurement set path not found: {ms_path}")
    if not is_ms_dir(ms_path):
        raise RuntimeError(f"Path is not a recognized measurement set directory: {ms_path}")

    project_code = project_code_override or infer_metadata_from_path(ms_path)[0]
    raise RuntimeError(
        "MS metadata extraction is not supported by this script. "
        "Provide an extracted SDM-BDF root instead, or use --project-code if you are passing an MS path."
        + (f" Inferred project code: {project_code}" if project_code else "")
    )


def parse_asdm_time(value):
    if value is None:
        return None

    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        if "T" in value:
            try:
                return datetime.fromisoformat(value).date().isoformat()
            except ValueError:
                pass
        if value.isdigit():
            value = int(value)
        else:
            try:
                value = float(value)
            except ValueError:
                return None

    if isinstance(value, int):
        if value > 1e15:
            days = value / 1e9 / 86400
        else:
            days = float(value)
    elif isinstance(value, float):
        if value > 1e5:
            days = value
        else:
            days = value
    else:
        return None

    mjd = days
    try:
        date = datetime(1858, 11, 17) + timedelta(days=mjd)
        return date.date().isoformat()
    except OverflowError:
        return None


def find_xml_file(root, filename):
    root = Path(root)
    for path in root.rglob(filename):
        if "Zone.Identifier" in str(path):
            continue
        return path
    return None


def iter_xml_files(root):
    root = Path(root)
    for path in root.rglob("*.xml"):
        if "Zone.Identifier" in str(path):
            continue
        yield path


def search_project_code_in_sdm(root):
    candidate_pattern = re.compile(r"\b[0-9]{2}[A-Z]-[0-9]{3}\b")
    tag_patterns = [
        re.compile(r"<projectCode>([^<]+)</projectCode>", re.I),
        re.compile(r"<projectName>([^<]+)</projectName>", re.I),
        re.compile(r"<projectId>([^<]+)</projectId>", re.I),
    ]

    for xml_path in iter_xml_files(root):
        try:
            text = xml_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        for tag_pat in tag_patterns:
            match = tag_pat.search(text)
            if match:
                candidate = match.group(1).strip()
                if candidate and candidate != "" and candidate_pattern.match(candidate):
                    return candidate

        match = candidate_pattern.search(text)
        if match:
            return match.group(0)

    return None


def extract_sdm_bdf_object_name(root):
    scan_file = find_xml_file(root, "Scan.xml")
    target_names = []
    if scan_file is not None:
        try:
            tree = ET.parse(scan_file)
            scan_root = tree.getroot()
            for row in scan_root.findall("row"):
                scan_intent = (row.findtext("scanIntent") or "").upper()
                source_name = (row.findtext("sourceName") or "").strip()
                if "OBSERVE_TARGET" in scan_intent and source_name:
                    target_names.append(source_name)
        except ET.ParseError:
            pass

    if target_names:
        return target_names[0]

    field_file = find_xml_file(root, "Field.xml")
    if field_file is not None:
        try:
            tree = ET.parse(field_file)
            field_root = tree.getroot()
            field_names = [
                (row.findtext("fieldName") or "").strip()
                for row in field_root.findall("row")
                if row.findtext("fieldName")
            ]
            if field_names:
                return field_names[-1]
        except ET.ParseError:
            pass

    return None


def extract_sdm_bdf_observation_date(root):
    scan_file = find_xml_file(root, "Scan.xml")
    if scan_file is None:
        return None

    start_times = []
    try:
        tree = ET.parse(scan_file)
        scan_root = tree.getroot()
        for row in scan_root.findall("row"):
            start_time = row.findtext("startTime")
            scan_intent = (row.findtext("scanIntent") or "").upper()
            if start_time is None:
                continue
            parsed_date = parse_asdm_time(start_time)
            if parsed_date is None:
                continue
            if "OBSERVE_TARGET" in scan_intent:
                return parsed_date
            start_times.append(parsed_date)
    except ET.ParseError:
        return None

    if start_times:
        return sorted(start_times)[0]
    return None


def extract_sdm_bdf_project_code(root, project_code_override=None):
    if project_code_override:
        return project_code_override

    code = search_project_code_in_sdm(root)
    if code:
        return code

    project_code, _, _ = infer_metadata_from_path(root)
    return project_code


def extract_sdm_bdf_metadata(root, project_code_override=None):
    root = Path(root)
    if not root.exists():
        raise FileNotFoundError(f"SDM-BDF path not found: {root}")

    project_code = extract_sdm_bdf_project_code(root, project_code_override)
    object_name = extract_sdm_bdf_object_name(root)
    observation_date = extract_sdm_bdf_observation_date(root)

    if project_code is None:
        raise RuntimeError(
            "Could not infer project code from the SDM-BDF content. "
            "Provide --project-code or use an SDM-BDF extraction with ObsProject metadata."
        )
    if object_name is None:
        raise RuntimeError("Could not infer object name from the SDM-BDF content.")
    if observation_date is None:
        raise RuntimeError("Could not infer observation date from the SDM-BDF content.")

    return project_code, object_name, observation_date


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


def extract_metadata(path, field_index=2, project_code_override=None):
    if is_ms_dir(path):
        return extract_ms_metadata(path, field_index=field_index, project_code_override=project_code_override)
    return extract_sdm_bdf_metadata(path, project_code_override=project_code_override)


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
    project_code, target, obs_date = extract_metadata(
        args.mspath,
        field_index=args.field,
        project_code_override=args.project_code,
    )

    output = {
        "project_code": project_code,
        "object_name": target,
        "observation_date": obs_date,
    }

    if args.rename and is_ms_dir(args.mspath):
        new_mspath = build_new_mspath(args.mspath, project_code, target, obs_date)
        rename_ms(args.mspath, new_mspath)
        output["renamed_path"] = str(new_mspath)

    if args.output_format == "json":
        print(json.dumps(output))
    else:
        print(project_code)
        print(target)
        print(obs_date)
        if args.rename and output.get("renamed_path"):
            print(str(output["renamed_path"]))


if __name__ == "__main__":
    main()
