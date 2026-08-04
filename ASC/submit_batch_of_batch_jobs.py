import os
import subprocess
import time
import sys

# Path to the file containing the list of batch scripts
batch_list_file = 'batch_files_list.txt'
cleanup_script_name = 'clean_up_post_selfcal_job.sh'

def _read_scripts(path):
    with open(path, 'r') as handle:
        return [line.strip() for line in handle if line.strip()]


def _sanitize_mpicasa_quiet(script_path):
    with open(script_path, 'r', encoding='utf-8') as handle:
        content = handle.read()

    updated = content.replace('mpicasa -quiet ', 'mpicasa ')
    if updated == content:
        return False

    with open(script_path, 'w', encoding='utf-8') as handle:
        handle.write(updated)

    print(f"Patched unsupported mpicasa -quiet in {script_path}")
    return True


def _submit_script(script_path, dependency=None):
    command = ['sbatch', '--parsable']
    if dependency:
        command.extend(['--dependency', dependency])
    command.append(script_path)

    result = subprocess.run(
        command,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )

    stdout_text = (result.stdout or '').strip()
    stderr_text = (result.stderr or '').strip()
    if stderr_text:
        print(stderr_text)

    # --parsable typically returns just the job id (or jobid;cluster).
    raw_id = stdout_text.split(';', 1)[0].strip() if stdout_text else ''
    if raw_id.isdigit():
        return raw_id
    return ''


if not os.path.exists(batch_list_file):
    print(f"Batch list file does not exist: {batch_list_file}")
    sys.exit(1)

scripts = _read_scripts(batch_list_file)
if not scripts:
    print(f"No scripts found in {batch_list_file}")
    sys.exit(1)

missing = [path for path in scripts if not os.path.exists(path)]
if missing:
    for path in missing:
        print(f"Script does not exist: {path}")
    sys.exit(1)

for path in scripts:
    _sanitize_mpicasa_quiet(path)

cleanup_candidates = [path for path in scripts if os.path.basename(path) == cleanup_script_name]
cleanup_script = cleanup_candidates[-1] if cleanup_candidates else None
frequency_scripts = [path for path in scripts if path != cleanup_script]

submitted_ids = []
submission_failures = []
id_parse_failures = []
for script_path in frequency_scripts:
    try:
        print(f"Submitting: {script_path}")
        job_id = _submit_script(script_path)
        if job_id:
            submitted_ids.append(job_id)
        else:
            print(f"Warning: could not parse job id for {script_path}")
            id_parse_failures.append(script_path)
        time.sleep(10)
    except subprocess.CalledProcessError as exc:
        print(f"Failed to submit {script_path}: {exc}")
        submission_failures.append(script_path)
        continue

if cleanup_script:
    dependency = None
    if submitted_ids:
        dependency = 'afterany:' + ':'.join(submitted_ids)
    try:
        if dependency:
            print(f"Submitting cleanup with dependency ({dependency}): {cleanup_script}")
        else:
            print(f"Submitting cleanup: {cleanup_script}")
        _submit_script(cleanup_script, dependency=dependency)
    except subprocess.CalledProcessError as exc:
        print(f"Failed to submit cleanup script {cleanup_script}: {exc}")
        sys.exit(1)

if submission_failures:
    print(
        f"Warning: {len(submission_failures)} frequency job(s) failed submission. "
        "Cleanup was still submitted for successfully submitted jobs."
    )
    sys.exit(1)

if id_parse_failures:
    print(
        f"Warning: could not parse job ids for {len(id_parse_failures)} frequency job(s). "
        "Cleanup dependency includes only parsed job ids."
    )
