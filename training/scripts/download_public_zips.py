"""Download keyless public dataset zips into training/datasets/raw/."""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "training" / "datasets" / "raw"

# slug, url, optional expected sha256 (empty = skip verify)
ZIPS: list[tuple[str, str, str]] = [
    (
        "leaf48_yolo_valorant_v3",
        "https://github.com/Leaf48/YOLO-Models-For-Valorant/releases/download/dataset-v3.0/dataset.zip",
        "",
    ),
]


def _download(url: str, dest_zip: Path) -> None:
    dest_zip.parent.mkdir(parents=True, exist_ok=True)
    req = Request(url, headers={"User-Agent": "valorant-montage-bot-dataset-fetch/1.0"})
    with urlopen(req, timeout=600) as resp, dest_zip.open("wb") as out:
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _extract(zip_path: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest)


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    for slug, url, expect_sha in ZIPS:
        dest = RAW / slug
        marker = dest / ".download_ok"
        if marker.is_file():
            print(f"skip {slug} (already downloaded)", flush=True)
            continue
        zip_path = RAW / f"_tmp_{slug}.zip"
        print(f"download {url} -> {slug}", flush=True)
        try:
            _download(url, zip_path)
            if expect_sha:
                got = _sha256(zip_path)
                if got != expect_sha:
                    raise RuntimeError(f"sha256 mismatch got={got}")
            if dest.exists():
                import shutil

                shutil.rmtree(dest)
            _extract(zip_path, dest)
            marker.write_text(f"{url}\n", encoding="utf-8")
            n_img = sum(1 for _ in dest.rglob("*.jpg")) + sum(1 for _ in dest.rglob("*.png"))
            print(f"ok {slug} images≈{n_img}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL {slug}: {type(exc).__name__}: {exc}", flush=True)
        finally:
            if zip_path.exists():
                zip_path.unlink()
    print(f"DONE raw_root={RAW}", flush=True)


if __name__ == "__main__":
    main()
