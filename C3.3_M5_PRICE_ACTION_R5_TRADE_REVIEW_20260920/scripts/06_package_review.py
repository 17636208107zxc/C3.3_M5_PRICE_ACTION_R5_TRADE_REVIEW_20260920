from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "06_PACKAGE/package_manifest.json"
ZIP_PATH = ROOT.parent / f"{ROOT.name}.zip"
SHA_PATH = ROOT.parent / f"{ROOT.name}.zip.sha256.txt"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def deliverable_files() -> list[Path]:
    return sorted(path for path in ROOT.rglob("*") if path.is_file() and path != PACKAGE and "__pycache__" not in path.parts)


def main() -> None:
    files = deliverable_files()
    manifest = {
        "package": ROOT.name,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "file_count_excluding_manifest": len(files),
        "files": [{"path": path.relative_to(ROOT).as_posix(), "size": path.stat().st_size, "sha256": sha256(path)} for path in files],
    }
    PACKAGE.parent.mkdir(exist_ok=True)
    PACKAGE.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(path for path in ROOT.rglob("*") if path.is_file() and "__pycache__" not in path.parts):
            archive.write(path, f"{ROOT.name}/{path.relative_to(ROOT).as_posix()}")
    zip_hash = sha256(ZIP_PATH)
    SHA_PATH.write_text(f"{zip_hash}  {ZIP_PATH.name}\n", encoding="ascii")
    print(json.dumps({"manifest_files": len(files), "zip": str(ZIP_PATH), "zip_size": ZIP_PATH.stat().st_size,
                      "zip_sha256": zip_hash, "sha_file": str(SHA_PATH)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
