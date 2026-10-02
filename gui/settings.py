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


EDGE_VOICES = ["th-TH-NiwatNeural", "th-TH-PremwadeeNeural"]
ENGINES = ["edge-tts", "gemini"]


@dataclass(frozen=True)
class VoiceSettings:
    engine: str
    voice_id: str
    style: str        # gemini only
    rate_pct: int     # "+10%" <-> 10


def voices_for(engine: str) -> list[str]:
    if engine == "gemini":
        import tts_gemini as G
        return G.GEMINI_VOICES
    return EDGE_VOICES


def default_voice(engine: str) -> str:
    if engine == "gemini":
        import tts_gemini as G
        return G.DEFAULT_VOICE
    return EDGE_VOICES[0]


def read_voice(storyboard: dict) -> VoiceSettings:
    v = {**R.DEFAULTS["voice"], **storyboard.get("voice", {})}
    return VoiceSettings(engine=v["engine"], voice_id=v["voice_id"], style=v["style"],
                         rate_pct=int(v["rate"].rstrip("%")))


def apply_voice(storyboard: dict, vs: VoiceSettings) -> dict:
    out = copy.deepcopy(storyboard)
    out["voice"] = {**out.get("voice", {}), "engine": vs.engine, "voice_id": vs.voice_id,
                    "style": vs.style, "rate": f"{vs.rate_pct:+d}%"}
    return out


def list_music(music_dir: Path = MUSIC_DIR) -> list[str]:
    if not music_dir.is_dir():
        return []
    return sorted(p.name for p in music_dir.iterdir() if p.suffix.lower() in AUDIO_EXTS)
