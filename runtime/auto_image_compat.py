from pathlib import Path


def patch_auto_image_output_directory(auto_image_dir: Path) -> None:
    helper_path = Path(auto_image_dir) / "helper_functions.py"
    run_path = Path(auto_image_dir) / "run-auto-image.py"

    helper_text = helper_path.read_text(encoding="utf-8")
    helper_replacements = (
        (
            "def set_up_filesystem(df_store, root_dir, try_point_source):",
            "def set_up_filesystem(df_store, root_dir, image_size, try_point_source):",
        ),
        (
            'os.makedirs(f"{root_dir}/images", exist_ok=True)',
            'os.makedirs(f"{root_dir}/images/{image_size}", exist_ok=True)',
        ),
        (
            'destination = f"{root_dir}/images" ',
            'destination = f"{root_dir}/images/{image_size}"',
        ),
    )
    for old, new in helper_replacements:
        if old in helper_text:
            helper_text = helper_text.replace(old, new, 1)
    helper_path.write_text(helper_text, encoding="utf-8")

    run_text = run_path.read_text(encoding="utf-8")
    run_text = run_text.replace(
        "set_up_filesystem(df_store, root_dir, try_point_source)",
        "set_up_filesystem(df_store, root_dir, image_size, try_point_source)",
        1,
    )
    run_path.write_text(run_text, encoding="utf-8")