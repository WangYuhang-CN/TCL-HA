"""Build an installable ZIP from an explicit allowlist, excluding local captures."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "tcl_plus"


def build_release(
    output_dir: Path = ROOT / "releases", *, expected_tag: str | None = None
) -> Path:
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    version = manifest["version"]
    if not isinstance(version, str) or not re.fullmatch(
        r"\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?", version
    ):
        raise ValueError("Manifest has an invalid release version")
    if expected_tag is not None and expected_tag != f"v{version}":
        raise ValueError(
            f"Tag {expected_tag} does not match manifest version v{version}"
        )
    files = [
        *COMPONENT.glob("*.py"),
        COMPONENT / "manifest.json",
        *COMPONENT.glob("translations/*.json"),
        *COMPONENT.glob("brand/*.png"),
        ROOT / "README.md",
        ROOT / "LICENSE",
    ]
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / f"tcl_plus-{version}.zip"
    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as bundle:
        for path in sorted(files):
            # Fixed timestamps make rebuilding the same source reproducible.
            info = ZipInfo(
                path.relative_to(ROOT).as_posix(), date_time=(1980, 1, 1, 0, 0, 0)
            )
            info.compress_type = ZIP_DEFLATED
            bundle.writestr(info, path.read_bytes())
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(
        f"{digest}  {archive.name}\n", encoding="ascii"
    )
    return archive


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tag", help="Validate the release tag against the manifest version"
    )
    args = parser.parse_args()
    try:
        print(build_release(expected_tag=args.tag))
    except ValueError as err:
        parser.error(str(err))
