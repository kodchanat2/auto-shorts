"""Storyboard prompt (wizard step 2). The text lives in docs/storyboard-prompt.md only."""
from __future__ import annotations

import re
from pathlib import Path

from render_shorts import SCRIPT_DIR

from .projects import Brief

PROMPT_DOC = SCRIPT_DIR / "docs" / "storyboard-prompt.md"
BLOCK_RE = re.compile(r"````text\n(.*?)````", re.S)


def load_template(path: Path = PROMPT_DOC) -> str:
    m = BLOCK_RE.search(path.read_text(encoding="utf-8"))
    if not m:
        raise ValueError(f"ไม่พบบล็อก ````text ใน {path}")
    return m.group(1).strip() + "\n"


def build_prompt(template: str, brief: Brief) -> str:
    out = re.sub(r"^หัวข้อ:.*$", f"หัวข้อ: {brief.topic.strip()}", template, count=1, flags=re.M)
    out = re.sub(r"^ความยาวเป้าหมาย:.*$", f"ความยาวเป้าหมาย: {brief.duration} วินาที", out, count=1, flags=re.M)
    out = re.sub(r"^โทน:.*$", f"โทน: {brief.tone.strip()}", out, count=1, flags=re.M)
    return re.sub(r'"target_duration_sec": \d+', f'"target_duration_sec": {brief.duration}', out)


def build_fix_prompt(errors: str) -> str:
    return ("storyboard ที่ส่งมาไม่ผ่านการตรวจของระบบ ช่วยแก้ตาม error ด้านล่าง "
            "แล้วส่ง JSON ฉบับเต็มกลับมาในบล็อกเดียว ไม่ต้องอธิบาย\n\n" + errors.strip() + "\n")
