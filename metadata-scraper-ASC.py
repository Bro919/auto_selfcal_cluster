import argparse
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

try:
    import casacore.tables as ct
    TABLE_BACKEND = "casacore"
except ImportError:
    ct = None
    try:
        import pyrap.tables as pt
        TABLE_BACKEND = "pyrap"
    except ImportError:
        pt = None
        TABLE_BACKEND = None


def parse_args():
    parser = argparse.ArgumentParser(
        description="Extract project code, object name, and observation date from a CASA measurement set."
    )
    parser.add_argument("mspath", help="Path to the measurement set directory")
    parser.add_argument(
        "--project-code",
        default=None,
        help="Project code override when it cannot be inferred from the MS content",
    )
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


def find_ms_directory(root_dir):
    root_dir = Path(root_dir)
    if is_ms_dir(root_dir):
        return root_dir

    if not root_dir.is_dir():
        return None

    direct_children = [child for child in root_dir.iterdir() if child.is_dir() and child.name.endswith(".ms")]
    if direct_children:
        return direct_children[0]

    recursive_children = [child for child in root_dir.rglob("*.ms") if child.is_dir()]
    return recursive_children[0] if recursive_children else None


def normalize_date_token(token):
    if token is None:
        return None
    token = str(token).strip()
    if not token:
        return None
    if re.match(r"^\d{4}-\d{2}-\d{2}$", token):
        return token
    m = re.match(r"^(\d{4})(\d{2})(\d{2})$", token)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r"^(\d{4})(\d{2})(\d{2})[-_].*$", token)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r"^(\d{5,6})(?:\.\d+)?$", token)
    if m:
        try:
            mjd = float(m.group(1))
        except ValueError:
            return None
        if mjd > 1000:
            try:
                return (datetime(1858, 11, 17) + timedelta(days=mjd)).date().isoformat()
            except OverflowError:
                return None
    return None


def is_missing_metadata_value(value):
    if value is None:
        return True
    text = str(value).strip()
    if not text:
        return True
    if text.lower() == "unknown":
        return True
    parts = [part for part in re.split(r"[._]+", text.lower()) if part]
    return bool(parts) and all(part == "unknown" for part in parts)


def infer_metadata_from_path(ms_path, project_code_override=None):
    project_code = project_code_override
    path = Path(ms_path)
    segments = [path.name] + [Path(seg).name for seg in path.parents]

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
        for candidate in [segment] + parts:
            maybe_date = normalize_date_token(candidate)
            if maybe_date:
                date_candidate = maybe_date
                if project_code is None and re.match(r'^[0-9]{2}[A-Z]-[0-9]{3}$', parts[0]):
                    project_code = parts[0]
                if len(parts) >= 3:
                    target_candidate = '.'.join(parts[1:-1])
                break
        if date_candidate is not None:
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

    if is_missing_metadata_value(target_candidate):
        target_candidate = None

    if target_candidate is None:
        parent_name = Path(ms_path).parent.name
        if (
            parent_name
            and parent_name != project_code
            and normalize_date_token(parent_name) is None
            and not is_missing_metadata_value(parent_name)
        ):
            target_candidate = parent_name

    if is_missing_metadata_value(target_candidate):
        target_candidate = None

    if date_candidate is None:
        for segment in segments:
            if "date" in segment.lower():
                maybe_date = normalize_date_token(segment)
                if maybe_date:
                    date_candidate = maybe_date
                    break

    return project_code, target_candidate, date_candidate


def open_ms_table(ms_path, table_name):
    ms_path = Path(ms_path)
    table_path = ms_path / table_name
    if not table_path.exists():
        raise FileNotFoundError(f"Measurement set table not found: {table_path}")

    if TABLE_BACKEND == "casacore":
        return ct.table(str(table_path), ack=False)
    if TABLE_BACKEND == "pyrap":
        return pt.table(str(table_path), readonly=True)
    raise RuntimeError(
        "No CASA measurement set backend is installed. Install casacore or pyrap to extract metadata from a .ms."
    )


def close_ms_table(table):
    try:
        table.close()
    except Exception:
        pass


def normalize_column_values(values):
    if values is None:
        return []
    if hasattr(values, "tolist"):
        try:
            values = values.tolist()
        except Exception:
            pass
    if isinstance(values, (list, tuple)):
        return values
    return [values]


def iter_values(value):
    if value is None:
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            yield from iter_values(item)
    else:
        yield value


def parse_ms_time(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        try:
            value = float(value)
        except ValueError:
            return normalize_date_token(value)

    try:
        value = float(value)
    except (TypeError, ValueError):
        return None

    if value > 1e14:
        days = value / 1e9 / 86400
    elif value > 1e8:
        days = value / 86400
    else:
        days = value

    if days < 1000:
        days = None
    if days is None:
        return None

    try:
        date = datetime(1858, 11, 17) + timedelta(days=days)
        return date.date().isoformat()
    except OverflowError:
        return None


def read_extracted_metadata_from_workdir(ms_path):
    metadata_file = Path(ms_path).parent / ".extracted_metadata"
    if not metadata_file.exists():
        return None
    values = {}
    try:
        with metadata_file.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key] = value
    except Exception:
        return None
    return values


def extract_ms_project_code(ms_path, project_code_override=None):
    if project_code_override:
        return project_code_override

    extracted = read_extracted_metadata_from_workdir(ms_path)
    if extracted and extracted.get("project_code"):
        return extracted["project_code"]

    project_code = None
    if TABLE_BACKEND:
        table = None
        try:
            table = open_ms_table(ms_path, "OBSERVATION")
            for column_name in ["PROJECT", "project", "PROJECT_ID", "PROJECTCODE"]:
                try:
                    values = normalize_column_values(table.getcol(column_name))
                except Exception:
                    continue
                for value in values:
                    if value is None:
                        continue
                    text = str(value).strip()
                    if text:
                        project_code = text
                        break
                if project_code:
                    break
        except Exception:
            pass
        finally:
            if table is not None:
                close_ms_table(table)

    if project_code is None:
        project_code = infer_metadata_from_path(ms_path, project_code_override)[0]
    return project_code


def extract_ms_object_name(ms_path):
    extracted = read_extracted_metadata_from_workdir(ms_path)
    if extracted and not is_missing_metadata_value(extracted.get("object_name")):
        return extracted["object_name"]

    object_name = None
    if TABLE_BACKEND:
        table = None
        try:
            table = open_ms_table(ms_path, "SOURCE")
            for column_name in ["NAME", "name", "CODE", "code"]:
                try:
                    values = normalize_column_values(table.getcol(column_name))
                except Exception:
                    continue
                for value in values:
                    if value is None:
                        continue
                    text = str(value).strip()
                    if not is_missing_metadata_value(text):
                        object_name = text
                        break
                if object_name:
                    break
        except Exception:
            pass
        finally:
            if table is not None:
                close_ms_table(table)

    if object_name is None:
        # Fallback to field table object name
        if TABLE_BACKEND:
            table = None
            try:
                table = open_ms_table(ms_path, "FIELD")
                for column_name in ["NAME", "name", "FIELD_NAME"]:
                    try:
                        values = normalize_column_values(table.getcol(column_name))
                    except Exception:
                        continue
                    for value in values:
                        if value is None:
                            continue
                        text = str(value).strip()
                        if not is_missing_metadata_value(text):
                            object_name = text
                            break
                    if object_name:
                        break
            except Exception:
                pass
            finally:
                if table is not None:
                    close_ms_table(table)

    if object_name is None:
        _, path_target, _ = infer_metadata_from_path(ms_path)
        object_name = path_target
    if is_missing_metadata_value(object_name):
        object_name = None
    return object_name


def extract_ms_observation_date(ms_path):
    extracted = read_extracted_metadata_from_workdir(ms_path)
    if extracted and extracted.get("observation_date"):
        return extracted["observation_date"]

    observation_date = None
    if TABLE_BACKEND:
        table = None
        try:
            table = open_ms_table(ms_path, "OBSERVATION")
            for column_name in ["TIME_RANGE", "TIME", "OBSERVATION_TIME", "DATE"]:
                try:
                    values = normalize_column_values(table.getcol(column_name))
                except Exception:
                    continue
                for value in values:
                    for item in iter_values(value):
                        parsed = parse_ms_time(item)
                        if parsed:
                            observation_date = parsed
                            break
                    if observation_date:
                        break
                if observation_date:
                    break
        except Exception:
            pass
        finally:
            if table is not None:
                close_ms_table(table)

    if observation_date is None:
        _, _, path_date = infer_metadata_from_path(ms_path)
        observation_date = path_date
    return observation_date


def extract_ms_metadata(ms_path, project_code_override=None):
    input_path = Path(ms_path)
    if not input_path.exists():
        raise FileNotFoundError(f"Measurement set path not found: {input_path}")

    ms_path = find_ms_directory(input_path)
    if ms_path is None:
        raise RuntimeError(
            f"Path is not a recognized measurement set directory and does not contain one: {input_path}"
        )

    project_code = extract_ms_project_code(ms_path, project_code_override)
    object_name = extract_ms_object_name(ms_path)
    observation_date = extract_ms_observation_date(ms_path)

    if project_code is None:
        raise RuntimeError(
            "Could not infer project code from the measurement set content. "
            "Provide --project-code or use a path containing the project code."
        )
    if object_name is None:
        raise RuntimeError("Could not infer object name from the measurement set content.")
    if observation_date is None:
        raise RuntimeError("Could not infer observation date from the measurement set content.")

    return project_code, object_name, observation_date


def main():
    args = parse_args()
    project_code, target, obs_date = extract_ms_metadata(
        args.mspath,
        project_code_override=args.project_code,
    )
    output = {
        "project_code": project_code,
        "object_name": target,
        "observation_date": obs_date,
    }
    if args.output_format == "json":
        print(json.dumps(output))
    else:
        print(project_code)
        print(target)
        print(obs_date)


if __name__ == "__main__":
    main()
