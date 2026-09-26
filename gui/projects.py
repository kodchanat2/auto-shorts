"""Project folders: naming, listing, brief (wizard step 1), storyboard text handling."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from render_shorts import FINAL_FILE, PROJECT_NAME_RE, PROJECTS_DIR, STORYBOARD_FILE

BRIEF_FILE = "brief.json"
CANDIDATE_FILE = "storyboard.candidate.json"
DEFAULT_DURATION = 45
VERSION_RE = re.compile(r"^[A-Za-z0-9_-]+$")
FENCE_RE = re.compile(r"```(?:json)?\s*\n(.*?)```", re.S)


@dataclass(frozen=True)
class Brief:
    topic: str
    tone: str
    duration: int = DEFAULT_DURATION


def validate_new_name(name: str, root: Path = PROJECTS_DIR) -> str | None:
    """Error message for an invalid/taken project name, or None if usable."""
    if not name:
        return "กรุณาใส่ชื่อ project"
    if not PROJECT_NAME_RE.match(name):
        return "ชื่อ project ใช้ได้เฉพาะ a–z, A–Z, 0–9, - และ _"
    if (root / name).exists():
        return f"project '{name}' มีอยู่แล้ว"
    return None


def list_projects(root: Path = PROJECTS_DIR) -> list[str]:
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir()
                  if p.is_dir() and ((p / STORYBOARD_FILE).exists() or (p / BRIEF_FILE).exists()))


def save_brief(project_dir: Path, brief: Brief) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / BRIEF_FILE).write_text(json.dumps(asdict(brief), ensure_ascii=False, indent=2),
                                          encoding="utf-8")


def load_brief(project_dir: Path) -> Brief | None:
    f = project_dir / BRIEF_FILE
    if not f.exists():
        return None
    data = json.loads(f.read_text(encoding="utf-8"))
    return Brief(topic=data.get("topic", ""), tone=data.get("tone", ""),
                 duration=int(data.get("duration", DEFAULT_DURATION)))


def extract_json(text: str) -> str:
    """Pull the storyboard JSON out of a Claude reply (fenced block or bare object).
    Returns it pretty-printed; raises ValueError if none parses."""
    m = FENCE_RE.search(text)
    body = m.group(1) if m else text
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("ไม่พบ JSON ในข้อความที่วาง")
    try:
        data = json.loads(body[start:end + 1])
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON ไม่ถูกต้อง: {e}") from e
    return json.dumps(data, ensure_ascii=False, indent=2)


def video_filename(name: str) -> str:
    """'' -> final.mp4, 'v2' -> v2.mp4 (the typed name replaces the default)."""
    name = name.strip()
    if not name:
        return FINAL_FILE
    if not VERSION_RE.match(name):
        raise ValueError("ชื่อไฟล์ใช้ได้เฉพาะ a–z, A–Z, 0–9, - และ _")
    return f"{name}.mp4"


def list_videos(project_dir: Path) -> list[Path]:
    vids = [p for p in project_dir.glob("*.mp4") if p.is_file()]
    return sorted(vids, key=lambda p: p.stat().st_mtime, reverse=True)
