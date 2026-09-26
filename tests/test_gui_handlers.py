import json

import pytest

import render_shorts as R
from gui import handlers as H
from gui import projects as P
from gui.cuts import CutInfo
from gui.settings import RenderSettings

EXAMPLE = (R.SCRIPT_DIR / "examples" / "storyboard.json").read_text(encoding="utf-8")


@pytest.fixture
def projects(tmp_path, monkeypatch):
    monkeypatch.setattr(H, "PROJECTS_DIR", tmp_path)
    return tmp_path


def test_check_and_save_accepts_claude_reply_with_fences(projects):
    res = H.check_and_save("clip", f"นี่คือ storyboard\n```json\n{EXAMPLE}\n```")
    assert res.ok, res.report
    assert "estimated" in res.report
    saved = projects / "clip" / "storyboard.json"
    assert json.loads(saved.read_text(encoding="utf-8"))["schema_version"] == "1.0"
    assert not (projects / "clip" / P.CANDIDATE_FILE).exists()


def test_check_and_save_rejects_schema_errors_without_touching_storyboard(projects):
    bad = json.loads(EXAMPLE)
    bad["scenes"][0]["role"] = "INTRO"
    res = H.check_and_save("clip", json.dumps(bad, ensure_ascii=False))
    assert not res.ok
    assert "INTRO" in res.report and "INTRO" in res.fix_prompt
    assert not (projects / "clip" / "storyboard.json").exists()


def test_check_and_save_rejects_text_without_json(projects):
    res = H.check_and_save("clip", "ขอโทษครับ ผมยังไม่ได้เขียน")
    assert not res.ok and "ไม่พบ JSON" in res.report and res.fix_prompt


def test_errors_and_warnings_parsing():
    out = "📄 Loading x\n  ⚠️  First scene is not HOOK\n\n❌ Storyboard errors:\n  • duplicate cut_id S1C1\n"
    assert H._errors_from(out) == "Storyboard errors:\n  • duplicate cut_id S1C1"
    assert H._warnings_from(out) == ["First scene is not HOOK"]
    assert H._errors_from("Traceback boom") == "Traceback boom"


def test_prompt_for_uses_brief(projects):
    assert H.prompt_for("none") == ""
    P.save_brief(projects / "clip", P.Brief("แมวกับกล่อง", "ตลก", 30))
    assert "หัวข้อ: แมวกับกล่อง" in H.prompt_for("clip")


def test_settings_and_cut_edits_round_trip(projects):
    (projects / "clip").mkdir()
    (projects / "clip" / "storyboard.json").write_text(EXAMPLE, encoding="utf-8")
    H.save_settings("clip", RenderSettings("a.mp3", 12.0, 0.4, 3.0, 1.5))
    data = H.read_storyboard("clip")
    assert data["bgm"]["start_sec"] == 12.0 and data["render"]["footage_speed"] == 1.5

    first = data["scenes"][0]["cuts"][0]["cut_id"]
    H.reroll_cut("clip", CutInfo(first, 0, 111, "", "q", 0.0, None))
    assert H.read_storyboard("clip")["scenes"][0]["cuts"][0]["exclude_video_ids"] == [111]


def test_save_settings_without_storyboard_raises(projects):
    with pytest.raises(FileNotFoundError):
        H.save_settings("missing", RenderSettings(None, 0, 0.5, 1.2, 2.0))


def test_outputs_readers(projects):
    folder = projects / "clip"
    folder.mkdir()
    assert H.timeline_warnings("clip") == [] and H.voice_preview("clip") is None
    assert H.storyboard_text("clip") == "" and H.read_storyboard("clip") is None
    (folder / "timeline.json").write_text(json.dumps({"scenes": [], "warnings": ["w1"]}))
    (folder / "voice_preview.wav").write_bytes(b"x")
    assert H.timeline_warnings("clip") == ["w1"]
    assert H.voice_preview("clip").endswith("voice_preview.wav")
    assert H.gallery("clip") == ([], [])


def test_check_result_includes_cut_plan(projects):
    res = H.check_and_save("clip", EXAMPLE)
    assert res.ok
    assert "[HOOK" in res.plan and "S1C1" in res.plan
    assert "Loading" not in res.plan


def test_clip_length_prefers_rendered_timeline(projects):
    folder = projects / "clip"
    folder.mkdir()
    assert H.clip_length("clip") == P.DEFAULT_DURATION
    (folder / "storyboard.json").write_text(json.dumps({"meta": {"target_duration_sec": 50}}))
    assert H.clip_length("clip") == 50
    (folder / "timeline.json").write_text(json.dumps({"duration_sec": 39.2}))
    assert H.clip_length("clip") == 39.2
