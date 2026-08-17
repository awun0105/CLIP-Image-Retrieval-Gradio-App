import shutil
import zipfile
from pathlib import Path

import database_utils
import pytest


def _clear_config_environment(monkeypatch):
    for key in database_utils.DEFAULTS:
        monkeypatch.delenv(key, raising=False)


def _write_artifacts(root: Path):
    (root / "DeepFashion/images").mkdir(parents=True)
    (root / "DeepFashion/embed_data").mkdir(parents=True)
    (root / "DeepFashion/embed_data/df.csv").write_text("image_path\na.jpg\n")
    (root / "DeepFashion/embed_data/df_image_embeds.npy").write_bytes(b"npy")
    (root / "DeepFashion/captions.json").write_text("{}")


def test_existing_dataset_skips_download(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _clear_config_environment(monkeypatch)
    _write_artifacts(tmp_path)
    monkeypatch.setattr(
        database_utils.urllib.request,
        "urlretrieve",
        lambda *_args: pytest.fail("download should be skipped"),
    )
    env = database_utils.download_and_prepare_dataset()
    assert env["INDEX_PATH"] == "./DeepFashion/embed_data"


def test_download_extracts_and_validates_default_layout(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _clear_config_environment(monkeypatch)
    source_archive = tmp_path / "source.zip"
    with zipfile.ZipFile(source_archive, "w") as archive:
        archive.writestr("DeepFashion/images/a.jpg", b"image")
        archive.writestr("DeepFashion/embed_data/df.csv", "image_path\na.jpg\n")
        archive.writestr("DeepFashion/embed_data/df_image_embeds.npy", b"npy")
        archive.writestr("DeepFashion/captions.json", "{}")

    def fake_download(_url, destination):
        shutil.copyfile(source_archive, destination)

    monkeypatch.setattr(database_utils.urllib.request, "urlretrieve", fake_download)
    database_utils.download_and_prepare_dataset()
    assert (tmp_path / "DeepFashion/images/a.jpg").exists()
    assert not (tmp_path / "DeepFashion.zip").exists()


def test_safe_extract_rejects_path_traversal(tmp_path):
    archive_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../outside.txt", "bad")
    with zipfile.ZipFile(archive_path) as archive:
        with pytest.raises(ValueError, match="Unsafe path"):
            database_utils._safe_extract(archive, tmp_path / "extract")


def test_custom_incomplete_paths_fail_without_download(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _clear_config_environment(monkeypatch)
    monkeypatch.setenv("DEFAULT_IMAGES_PATH", "custom/images")
    with pytest.raises(FileNotFoundError, match="Custom dataset paths are incomplete"):
        database_utils.download_and_prepare_dataset()
