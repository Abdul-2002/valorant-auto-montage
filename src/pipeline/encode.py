"""Encoder settings and the ffmpeg finishing chain (LUT, sharpen, grain, vignette)."""

from __future__ import annotations

import re
from pathlib import Path

from src.config.models import OutputConfig
from src.effects.looks import write_cube_lut


def _parse_mbps(rate: str) -> float:
    m = re.fullmatch(r"\s*([\d.]+)\s*([kKmM]?)\s*", str(rate))
    if not m:
        raise ValueError(f"invalid bitrate: {rate!r}")
    value = float(m.group(1))
    return value / 1000.0 if m.group(2).lower() == "k" else value


def rate_args(rate: str) -> list[str]:
    """Target bitrate with headroom for fast gameplay motion."""
    mbps = _parse_mbps(rate)
    return ["-b:v", f"{mbps:g}M", "-maxrate", f"{mbps * 1.5:g}M", "-bufsize", f"{mbps * 2:g}M"]


def _filter_path(path: Path) -> str:
    """ffmpeg filter-arg escaping for Windows paths (drive colon, backslashes)."""
    return "'" + path.resolve().as_posix().replace(":", "\\:") + "'"


def resolve_lut(cfg: OutputConfig, work_dir: Path) -> Path | None:
    if not cfg.lut:
        return None
    if cfg.lut == "procedural":
        return write_cube_lut(work_dir / "look_teal_orange.cube")
    path = Path(cfg.lut)
    if not path.is_file():
        raise FileNotFoundError(f"output.lut not found: {path}")
    return path


def finishing_filters(cfg: OutputConfig, lut_path: Path | None) -> str | None:
    """Single-input/single-output filtergraph applied while encoding the 16:9 master."""
    chain: list[str] = []
    if lut_path is not None and cfg.lut_strength > 0.0:
        lut = f"lut3d=file={_filter_path(lut_path)}:interp=tetrahedral"
        if cfg.lut_strength >= 0.999:
            chain.append(lut)
        else:
            chain.append(f"split[base][look];[look]{lut}[graded];[base][graded]blend=all_mode=normal:all_opacity={cfg.lut_strength:g}")
    if cfg.sharpen > 0.0:
        chain.append(f"unsharp=5:5:{cfg.sharpen:g}:5:5:0")
    if cfg.vignette:
        chain.append("vignette=angle=PI/6")
    if cfg.grain > 0:
        chain.append(f"noise=alls={cfg.grain}:allf=t")
    return ",".join(chain) if chain else None


def master_ffmpeg_params(cfg: OutputConfig, lut_path: Path | None) -> list[str]:
    params = rate_args(cfg.video_bitrate)
    filters = finishing_filters(cfg, lut_path)
    if filters:
        params += ["-vf", filters]
    return params + ["-pix_fmt", "yuv420p"]
