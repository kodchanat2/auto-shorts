"""Per-cut review: thumbnails from timeline.json + cached footage, re-roll edits."""
from __future__ import annotations

import copy
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

THUMB_W, THUMB_H = 270, 480
THUMB_OFFSET_SEC = 0.5   # seconds into the cut (output time) used for the thumbnail


@dataclass(frozen=True)
class CutInfo:
    cut_id: str
    variant: int
    video_id: int
    url: str
    query: str
    src_start: float
    local: Path | None

    @property
    def label(self) -> str:
        return self.cut_id + "′" * self.variant


def load_cuts(project_dir: Path) -> list[CutInfo]:
    tl = project_dir / "timeline.json"
    if not tl.exists():
        return []
    data = json.loads(tl.read_text(encoding="utf-8"))
    footage = project_dir / "cache" / "pexels" / "footage"
    out = []
    for scene in data.get("scenes", []):
        for c in scene.get("cuts", []):
            vid = c.get("pexels_video_id")
            if vid is None:
                continue
            local = next(iter(sorted(footage.glob(f"pexels_{vid}_*.mp4"))), None)
            out.append(CutInfo(cut_id=c["cut_id"], variant=c.get("variant", 0), video_id=vid,
                               url=c.get("pexels_url") or "", query=c.get("query_used", ""),
                               src_start=float(c.get("source_start_sec") or 0.0), local=local))
    return out


def thumbnail(cut: CutInfo, project_dir: Path, speed: float) -> Path | None:
    """Frame the viewer actually sees near the start of the cut, center-cropped 9:16."""
    if cut.local is None:
        return None
    t = cut.src_start + THUMB_OFFSET_SEC * speed
    out = project_dir / "cache" / "thumbs" / f"{cut.video_id}_{t:.2f}.jpg"
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    vf = (f"scale={THUMB_W}:{THUMB_H}:force_original_aspect_ratio=increase,"
          f"crop={THUMB_W}:{THUMB_H}")
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(cut.local),
                        "-frames:v", "1", "-vf", vf, str(out)], capture_output=True, text=True)
    return out if r.returncode == 0 and out.exists() else None


def _edit_cut(storyboard: dict, cut_id: str, fn) -> dict:
    out = copy.deepcopy(storyboard)
    for scene in out.get("scenes", []):
        for c in scene.get("cuts", []):
            if c.get("cut_id") == cut_id:
                fn(c)
                return out
    raise KeyError(cut_id)


def reroll(storyboard: dict, cut_id: str, current_id: int) -> dict:
    """Never use current_id for this cut again; the renderer then picks the next best clip."""
    def fn(c):
        c.pop("pexels_video_id", None)
        ex = c.get("exclude_video_ids", [])
        c["exclude_video_ids"] = ex if current_id in ex else [*ex, current_id]
    return _edit_cut(storyboard, cut_id, fn)

