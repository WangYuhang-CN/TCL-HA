"""Ensure the distributable contains only install files, README and license."""

import hashlib
import importlib.util
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_builder():
    spec = importlib.util.spec_from_file_location(
        "build_release", ROOT / "scripts/build_release.py"
    )
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    return builder


def test_release_contents_integrity_and_reproducibility(tmp_path):
    builder = load_builder()
    archive = builder.build_release(tmp_path)
    original = archive.read_bytes()
    digest = hashlib.sha256(original).hexdigest()
    assert (
        archive.with_suffix(".zip.sha256").read_text() == f"{digest}  {archive.name}\n"
    )
    with ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        names = bundle.namelist()
        assert all(
            name.startswith("custom_components/tcl_plus/")
            or name in {"README.md", "LICENSE"}
            for name in names
        )
        assert not any(
            part.startswith(".") or part == "__pycache__"
            for name in names
            for part in Path(name).parts
        )
        assert (
            json.loads(bundle.read("custom_components/tcl_plus/manifest.json"))[
                "version"
            ]
            == json.loads(
                (ROOT / "custom_components/tcl_plus/manifest.json").read_text(
                    encoding="utf-8"
                )
            )["version"]
        )
        assert "custom_components/tcl_plus/capabilities.py" in names
        assert "custom_components/tcl_plus/brand/icon.png" in names
        assert bundle.read("README.md") == (ROOT / "README.md").read_bytes()
        assert bundle.read("LICENSE") == (ROOT / "LICENSE").read_bytes()
    builder.build_release(tmp_path)
    assert archive.read_bytes() == original


def test_release_rejects_mismatched_tag_before_creating_output(tmp_path):
    destination = tmp_path / "output"
    with pytest.raises(ValueError, match="does not match manifest"):
        load_builder().build_release(destination, expected_tag="v999.0.0")
    assert not destination.exists()


def test_tagged_build_outputs_only_package_and_checksum(tmp_path):
    version = json.loads(
        (ROOT / "custom_components/tcl_plus/manifest.json").read_text(encoding="utf-8")
    )["version"]
    archive = load_builder().build_release(tmp_path, expected_tag=f"v{version}")
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        archive.name,
        f"{archive.name}.sha256",
    ]
