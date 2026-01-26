import argparsefrom 
from pathlib import Path
import shutil
import tarfile
import sys
import urllib.request

def download_progress(blocks, block_size, total_size):
    if total_size <= 0:
        return
    downloaded = blocks * block_size
    percent = min(downloaded / total_size * 100, 100)\
        
    mb_done = downloaded / (1024 * 1024)
    mb_total = total_size / (1024 * 1024)

    print(
        f"\rDownloading: {percent:5.1f}% ({mb_done:6.1f} MB / {mb_total:.1f} MB)",
        end='',
        flush=True
    )

def main():
    parser = argparse.ArgumentParser(
        description="Download and extract a tar file from a URL."
    )

    parser.add_argument("directory", help="directoy to create and work in")
    parser.add_argument("url", help="URL of the tar file to download")
    parser.add_argument("extracted_file", help="File to move out after extraction")
    parser.add_argument("output_name", help="Name of the output file after moving")

    args = parser.parse_args()

    # Create working directory, from given path
    workdir = Path(args.directory)
    workdir.mkdir(parents=True, exist_ok=True)

    # Download the tar file
    tar_name= Path(args.url).name
    tar_path = workdir / tar_name

    print(f"Downloading {args.url} to {tar_path}")
    urllib.request.urlretrieve(
        args.url,
        tar_path,
        reporthook=download_progress
    )
    print("\nDownload complete.")

    # Extract the tar file and move the specified file
    with tarfile.open(tar_path, "r:*") as tar:
        tar.extractall(path=workdir)
        print(f"Extracted {tar_name} to {workdir}")

    source_extracted = workdir / args.extracted_file
    if not source_extracted.exists():
        sys.exit(f"Error: Extracted file {args.extracted_file} not found in {workdir}")

    shutil.move(source_extracted, args.output_name)

    print(f"Moved {source_extracted} to {args.output_name}")
    print("Process completed successfully.")

if __name__ == "__main__":
    main()