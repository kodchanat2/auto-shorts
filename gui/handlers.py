"""GUI actions that touch disk or subprocesses. No Gradio imports: returns plain values."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from render_shorts import PROJECTS_DIR, STORYBOARD_FILE

from . import cuts as C
from . import projects as P
from . import prompt as PR
from . import runner as RU
from . import settings as S

VALIDATE_TIMEOUT_SEC = 60


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    report: str          # human-readable summary (Markdown)
    fix_prompt: str      # text to paste back to Claude when not ok
    plan: str = ""       # dry-run scene/cut plan (when ok)


def project_dir(name: str) -> Path:
    return PROJECTS_DIR / name


def prompt_for(name: str) -> str:
    brief = P.load_brief(project_dir(name))
    return PR.build_prompt(PR.load_template(), brief) if brief else ""


def _dry_run(target: Path) -> tuple[int, str]:
    r = subprocess.run(RU.build_command(str(target), "dry"), cwd=RU.R.SCRIPT_DIR,
                       capture_output=True, text=True, timeout=VALIDATE_TIMEOUT_SEC)
    return r.returncode, r.stdout + r.stderr


def _errors_from(output: str) -> str:
    lines = output.splitlines()
    start = next((i for i, l in enumerate(lines) if l.startswith("❌")), None)
    if start is None:
        return output.strip()[-2000:]
    return "\n".join(lines[start:]).replace("❌ ", "").strip()


def _plan_from(output: str) -> str:
    """Scene/cut plan section of the dry-run log (between the title line and the result)."""
    lines = output.splitlines()
    start = next((i for i, l in enumerate(lines) if l.startswith("🎬")), None)
    if start is None:
        return ""
    body = [l for l in lines[start:] if not l.startswith("✅") and "⚠️" not in l]
    return "\n".join(body).strip()


def _warnings_from(output: str) -> list[str]:
    return [l.strip().replace("⚠️  ", "") for l in output.splitlines() if "⚠️" in l]


def check_and_save(name: str, pasted: str) -> CheckResult:
    """Extract JSON from pasted text, validate with render_shorts --dry-run, save if valid."""
    try:
        text = P.extract_json(pasted)
    except ValueError as e:
        return CheckResult(False, f"❌ {e}", PR.build_fix_prompt(str(e)))
    folder = project_dir(name)
    folder.mkdir(parents=True, exist_ok=True)
    candidate = folder / P.CANDIDATE_FILE
    candidate.write_text(text + "\n", encoding="utf-8")
    code, out = _dry_run(candidate)
    if code != 0:
        errors = _errors_from(out)
        return CheckResult(False, f"❌ storyboard ยังไม่ผ่าน\n\n```\n{errors}\n```", PR.build_fix_prompt(errors))
    candidate.replace(folder / STORYBOARD_FILE)
    est = next((l.strip() for l in out.splitlines() if "estimated" in l), "")
    warns = _warnings_from(out)
    report = "✅ บันทึก storyboard แล้ว" + (f"  ·  {est}" if est else "")
    if warns:
        report += "\n\n**Warnings**\n" + "\n".join(f"- {w}" for w in warns)
    return CheckResult(True, report, "", _plan_from(out))


def read_storyboard(name: str) -> dict | None:
    f = project_dir(name) / STORYBOARD_FILE
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def storyboard_text(name: str) -> str:
    f = project_dir(name) / STORYBOARD_FILE
    return f.read_text(encoding="utf-8") if f.exists() else ""


def write_storyboard(name: str, data: dict) -> str:
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    (project_dir(name) / STORYBOARD_FILE).write_text(text, encoding="utf-8")
    return text


def save_settings(name: str, s: S.RenderSettings) -> str:
    data = read_storyboard(name)
    if data is None:
        raise FileNotFoundError(STORYBOARD_FILE)
    return write_storyboard(name, S.apply_settings(data, s))


def clip_length(name: str) -> float:
    """Seconds of music the clip will use: last render's length, else the storyboard target."""
    tl = project_dir(name) / "timeline.json"
    if tl.exists():
        dur = json.loads(tl.read_text(encoding="utf-8")).get("duration_sec")
        if dur:
            return float(dur)
    data = read_storyboard(name) or {}
    return float(data.get("meta", {}).get("target_duration_sec", P.DEFAULT_DURATION))


def timeline_warnings(name: str) -> list[str]:
    tl = project_dir(name) / "timeline.json"
    if not tl.exists():
        return []
    return json.loads(tl.read_text(encoding="utf-8")).get("warnings", [])


def voice_preview(name: str) -> str | None:
    f = project_dir(name) / "voice_preview.wav"
    return str(f) if f.exists() else None


def gallery(name: str) -> tuple[list[tuple[str, str]], list[C.CutInfo]]:
    """Thumbnails for the last render plus the matching CutInfo list (same order)."""
    folder = project_dir(name)
    data = read_storyboard(name) or {}
    speed = S.read_settings(data).footage_speed
    items, infos = [], []
    for cut in C.load_cuts(folder):
        thumb = C.thumbnail(cut, folder, speed)
        if thumb:
            items.append((str(thumb), f"{cut.label} · #{cut.video_id}"))
            infos.append(cut)
    return items, infos


def reroll_cut(name: str, cut: C.CutInfo) -> str:
    return write_storyboard(name, C.reroll(read_storyboard(name) or {}, cut.cut_id, cut.video_id))

