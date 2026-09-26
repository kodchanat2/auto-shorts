"""Render options exposed in the GUI, stored back into the storyboard."""
from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path

import render_shorts as R

MUSIC_DIR = R.SCRIPT_DIR / "music"
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}


@dataclass(frozen=True)
class RenderSettings:
    music: str | None       # None = pick by seed
    start_sec: float
    volume: float
    duck_ratio: float
    footage_speed: float


def read_settings(storyboard: dict) -> RenderSettings:
    bgm = {**R.DEFAULTS["bgm"], **storyboard.get("bgm", {})}
    render = {**R.DEFAULTS["render"], **storyboard.get("render", {})}
    return RenderSettings(music=bgm["file"], start_sec=bgm["start_sec"], volume=bgm["volume"],
                          duck_ratio=bgm["duck_ratio"], footage_speed=render["footage_speed"])


def apply_settings(storyboard: dict, s: RenderSettings) -> dict:
    out = copy.deepcopy(storyboard)
    out["bgm"] = {**out.get("bgm", {}), "file": s.music, "start_sec": s.start_sec,
                  "volume": s.volume, "duck_ratio": s.duck_ratio}
    out["render"] = {**out.get("render", {}), "footage_speed": s.footage_speed}
    return out


def list_music(music_dir: Path = MUSIC_DIR) -> list[str]:
    if not music_dir.is_dir():
        return []
    return sorted(p.name for p in music_dir.iterdir() if p.suffix.lower() in AUDIO_EXTS)
