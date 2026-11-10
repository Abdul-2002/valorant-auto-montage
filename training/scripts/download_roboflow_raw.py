"""Download Roboflow Universe datasets into training/datasets/raw/ for re-annotation.

Requires ROBOFLOW_API_KEY (or ROBOFLOW_KEY) in the environment or repo `.env`.
Never prints the key. Class taxonomies may differ — that is intentional.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "training" / "datasets" / "raw"

# workspace, project, preferred_version, local slug
# Prefer largest / latest versions. Version fallbacks handled at download time.
DATASETS: list[tuple[str, str, int, str]] = [
    # HUD / kill banner / spectating (primary for re-label)
    ("suman-kumar-dx18l", "valorant-kill-banner-woebs", 1, "valorant_kill_banner"),
    ("suman-kumar-dx18l", "valorant-spectating", 1, "valorant_spectating"),
    ("christalin-dorsey-ljvjf", "simple-valorant-ui-detector", 1, "simple_valorant_ui"),
    ("valorant-kill-banner-detection", "valorant-kill-banner-detection-alwsr", 3, "kill_banner_detection_alwsr"),
    ("detect-qa7ry", "valorant-kill-banner-zuu0v", 1, "detect_kill_banner_zuu0v"),
    ("clipmaker", "valorant-kill-feed-detector-vsayu", 4, "kill_feed_detector_v4"),
    ("valorant-killfeed", "valorant-killfeed", 3, "valorant_killfeed_39"),
    ("valorant-wwdj4", "yolo-all-av4di", 1, "yolo_all_death_kills"),
    # Killfeed + world (large — re-label yourself)
    ("kasaden", "valorant-test-tz2g5-zu96f", 10, "kasaden_valorant_test"),
    ("valorantkills", "valorant-kills-llb5g", 9, "valorant_kills_llb5g"),
    # Agents / spike / bodies (volume for hard-neg / future heads)
    ("daniels-magonis-0pjzx", "valorant-9ufcp", 3, "daniels_valorant_9ufcp"),
    ("matthew-watkins-hugkx", "people-valorant", 1, "people_valorant"),
    ("ai-evhra", "valorant-9lnsh", 3, "ai_valorant_9lnsh"),
    ("arif-kobel-dzirq", "valorant-kns89", 1, "arif_valorant_kns89"),
    ("tim-olson-rvtpl", "kota3", 3, "kota3"),
    ("om-kulkarni-1f0wf", "custom-model-3", 1, "custom_model_3"),
    ("rishabh-miniclip-gkn5v", "-b8t19", 1, "b8t19_enemy"),
    ("wesh", "valorant-jsq9e", 1, "wesh_valorant_enemies"),
]


def _load_dotenv() -> None:
    """Load repo `.env` into os.environ without printing values."""
    env_path = REPO / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = val


def _api_key() -> str:
    _load_dotenv()
    key = (os.environ.get("ROBOFLOW_API_KEY") or os.environ.get("ROBOFLOW_KEY") or "").strip()
    if not key:
        raise SystemExit(
            "ROBOFLOW_API_KEY missing. Create a free key at https://roboflow.com "
            "and set it in the environment or .env (do not commit it)."
        )
    return key


def _move_into(dest: Path, src: Path) -> None:
    for item in src.iterdir():
        target = dest / item.name
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        shutil.move(str(item), str(target))


def _download_version(
    rf: object,
    workspace: str,
    project: str,
    version: int,
    slug: str,
    dest: Path,
) -> None:
    work = RAW / f"_dl_{slug}"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    prev = Path.cwd()
    os.chdir(work)
    try:
        proj = rf.workspace(workspace).project(project)
        ver = proj.version(version)
        dataset = ver.download("yolov8")
        src = Path(getattr(dataset, "location", None) or work)
        if not src.exists():
            kids = [p for p in work.iterdir() if p.is_dir()]
            if not kids:
                raise RuntimeError("download produced no folder")
            src = kids[0]
        _move_into(dest, src)
    finally:
        os.chdir(prev)
        shutil.rmtree(work, ignore_errors=True)


def _download_one(
    rf: object,
    workspace: str,
    project: str,
    version: int,
    slug: str,
) -> None:
    dest = RAW / slug
    dest.mkdir(parents=True, exist_ok=True)
    marker = dest / ".download_ok"
    if marker.is_file():
        print(f"skip {slug} (already downloaded)", flush=True)
        return

    versions_to_try = list(range(version, 0, -1))
    last_err: Exception | None = None
    for ver in versions_to_try:
        print(f"download {workspace}/{project} v{ver} -> {dest}", flush=True)
        try:
            _download_version(rf, workspace, project, ver, slug, dest)
            marker.write_text(f"{workspace}/{project}/{ver}\n", encoding="utf-8")
            n_img = sum(1 for _ in dest.rglob("*.jpg")) + sum(1 for _ in dest.rglob("*.png"))
            print(f"ok {slug} version={ver} images≈{n_img}", flush=True)
            return
        except Exception as exc:  # noqa: BLE001 — keep going across packs/versions
            last_err = exc
            print(f"retry {slug} v{ver}: {type(exc).__name__}: {exc}", flush=True)
            # Clean partial dest contents except marker attempts
            for item in list(dest.iterdir()):
                if item.name == ".download_ok":
                    continue
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()

    print(f"FAIL {slug}: {type(last_err).__name__}: {last_err}", flush=True)


def main() -> None:
    try:
        from roboflow import Roboflow
    except ImportError as exc:
        raise SystemExit("pip install roboflow") from exc

    key = _api_key()
    print(f"key_present=True key_len={len(key)} datasets={len(DATASETS)}", flush=True)
    RAW.mkdir(parents=True, exist_ok=True)
    rf = Roboflow(api_key=key)
    for workspace, project, version, slug in DATASETS:
        _download_one(rf, workspace, project, version, slug)
    print(f"DONE raw_root={RAW}", flush=True)


if __name__ == "__main__":
    main()
