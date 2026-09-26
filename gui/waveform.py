"""Music timing helpers for the start-offset control (player waveform does the drawing)."""
from __future__ import annotations

import subprocess
from pathlib import Path


def duration(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def used_span(start: float, clip_len: float, total: float) -> tuple[float, float]:
    s = max(0.0, min(start, total))
    return s, min(total, s + clip_len)


def _mmss(sec: float) -> str:
    sec = max(0, int(round(sec)))
    return f"{sec // 60}:{sec % 60:02d}"


def caption(start: float, clip_len: float, total: float) -> str:
    s, e = used_span(start, clip_len, total)
    return f"เริ่ม {_mmss(s)} · ช่วงที่ใช้ {_mmss(s)}–{_mmss(e)} จากทั้งหมด {_mmss(total)}"
