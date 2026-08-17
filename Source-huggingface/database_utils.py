"""Download and validate the DeepFashion artifacts used by the Space."""

from __future__ import annotations

import os
import shutil
import urllib.request
import uuid
import zipfile
from pathlib import Path

from dotenv import dotenv_values

DEFAULTS = {
    "DEFAULT_IMAGES_PATH": "./DeepFashion/images",
    "INDEX_PATH": "./DeepFashion/embed_data",
    "CAPTIONS_PATH": "./DeepFashion/captions.json",
    "HUGGINGFACE_HUB_CACHE": "./hf_cache",
    "DATASET_ZIP_URL": (
        "https://huggingface.co/datasets/anhquanlam/"
        "clip-deepfashion-multimodal/resolve/main/DeepFashion.zip"
    ),
    "MODEL_ID": "anhquanlam/clip-finetuned-deepfashion",
    "SCAN_BATCH_SIZE": "16",
}


def load_environment(dotenv_path: str | Path = ".env") -> dict[str, str]:
    """Load defaults, then dotenv values, then real environment variables."""
    values = dict(DEFAULTS)
    path = Path(dotenv_path)
    if path.exists():
        values.update({key: value for key, value in dotenv_values(path).items() if value})
    for key in DEFAULTS:
        if os.environ.get(key):
            values[key] = os.environ[key]
    return values


def _required_paths(env: dict[str, str]) -> tuple[Path, Path, Path, Path]:
    images_path = Path(env["DEFAULT_IMAGES_PATH"])
    index_path = Path(env["INDEX_PATH"])
    return (
        images_path,
        index_path / "df.csv",
        index_path / "df_image_embeds.npy",
        Path(env["CAPTIONS_PATH"]),
    )


def _missing_artifacts(env: dict[str, str]) -> list[Path]:
    images_path, dataframe_path, embeddings_path, captions_path = _required_paths(env)
    required = [images_path, dataframe_path, embeddings_path, captions_path]
    return [path for path in required if not path.exists()]


def _safe_extract(archive: zipfile.ZipFile, destination: Path) -> None:
    destination = destination.resolve()
    for member in archive.infolist():
        target = (destination / member.filename).resolve()
        if target != destination and destination not in target.parents:
            raise ValueError(f"Unsafe path in dataset archive: {member.filename}")
    archive.extractall(destination)


def _find_extracted_dataset(staging_dir: Path) -> Path:
    candidates = [staging_dir / "DeepFashion", staging_dir]
    for candidate in candidates:
        required = [
            candidate / "images",
            candidate / "embed_data/df.csv",
            candidate / "embed_data/df_image_embeds.npy",
            candidate / "captions.json",
        ]
        if all(path.exists() for path in required):
            return candidate
    raise FileNotFoundError("Downloaded archive does not contain DeepFashion artifacts")


def _install_default_dataset(staged_dataset: Path, target: Path) -> None:
    """Replace an incomplete default dataset while retaining a rollback copy."""
    backup = target.with_name(f".{target.name}.backup-{uuid.uuid4().hex}")
    had_target = target.exists()
    try:
        if had_target:
            os.replace(target, backup)
        os.replace(staged_dataset, target)
    except Exception:
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        if backup.exists():
            os.replace(backup, target)
        raise
    else:
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)


def download_and_prepare_dataset() -> dict[str, str]:
    """Ensure the legacy DeepFashion ZIP artifacts are available locally."""
    env = load_environment()
    os.environ["HUGGINGFACE_HUB_CACHE"] = env["HUGGINGFACE_HUB_CACHE"]

    missing = _missing_artifacts(env)
    if not missing:
        print("Dataset artifacts already exist. Skipping download.")
        return env

    default_layout = (
        Path(env["DEFAULT_IMAGES_PATH"]) == Path(DEFAULTS["DEFAULT_IMAGES_PATH"])
        and Path(env["INDEX_PATH"]) == Path(DEFAULTS["INDEX_PATH"])
        and Path(env["CAPTIONS_PATH"]) == Path(DEFAULTS["CAPTIONS_PATH"])
    )
    if not default_layout:
        missing_text = ", ".join(str(path) for path in missing)
        raise FileNotFoundError(
            "Custom dataset paths are incomplete and cannot be replaced automatically: "
            f"{missing_text}"
        )

    archive_path = Path("DeepFashion.zip")
    partial_path = archive_path.with_suffix(".zip.part")
    if not archive_path.exists():
        print("Downloading DeepFashion.zip from Hugging Face Dataset...")
        urllib.request.urlretrieve(env["DATASET_ZIP_URL"], partial_path)
        os.replace(partial_path, archive_path)

    staging_dir = Path(f".deepfashion-extract-{uuid.uuid4().hex}")
    staging_dir.mkdir(parents=True)
    try:
        print("Extracting DeepFashion.zip...")
        try:
            with zipfile.ZipFile(archive_path, "r") as archive:
                _safe_extract(archive, staging_dir)
        except zipfile.BadZipFile:
            archive_path.unlink(missing_ok=True)
            raise
        staged_dataset = _find_extracted_dataset(staging_dir)
        _install_default_dataset(staged_dataset, Path("DeepFashion"))
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)

    missing = _missing_artifacts(env)
    if missing:
        missing_text = ", ".join(str(path) for path in missing)
        raise FileNotFoundError(
            f"Dataset extraction completed but artifacts are missing: {missing_text}"
        )

    archive_path.unlink(missing_ok=True)
    print(f"Using images path: {env['DEFAULT_IMAGES_PATH']}")
    print(f"Using index path: {env['INDEX_PATH']}")
    return env
