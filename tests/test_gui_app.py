import pytest

import gui.app as A
from gui import handlers as H
from gui import projects as P
from gui.cuts import CutInfo
from gui.theme import progress_bar


@pytest.fixture
def projects(tmp_path, monkeypatch):
    monkeypatch.setattr(H, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(P, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(P.validate_new_name, "__defaults__", (tmp_path,))
    return tmp_path


def test_progress_bar_clamps_and_escapes():
    html = progress_bar(1.7, "<b>x</b>", "ok")
    assert 'data-state="ok"' in html and "scaleX(1.000)" in html and "100%" in html
    assert "&lt;b&gt;" in html


@pytest.mark.parametrize("args, msg", [
    (("bad name", "t", "tone", 45, ""), "ชื่อ project"),
    (("ok", "", "tone", 45, ""), "เนื้อหา"),
    (("ok", "topic", "", 45, ""), "โทน"),
])
def test_wizard_step1_validation(projects, args, msg):
    out = A.wizard_step1(*args)
    assert msg in out[A.step1_msg]


def test_wizard_step1_saves_brief_and_builds_prompt(projects):
    out = A.wizard_step1("cat_box", "แมวกับกล่อง", "ตลก", 30, "")
    assert out[A.wiz_state] == "cat_box"
    assert "หัวข้อ: แมวกับกล่อง" in out[A.prompt_box]
    assert P.load_brief(projects / "cat_box") == P.Brief("แมวกับกล่อง", "ตลก", 30)
    # going back and resubmitting the same wizard project is allowed
    assert A.step1_msg in A.wizard_step1("cat_box", "แมว", "ตลก", 30, "cat_box")


def test_wizard_step3_requires_step1():
    assert "ขั้นที่ 1" in A.wizard_step3("", "{}")[A.step3_msg]


def test_guards_without_selection():
    assert "เลือกคัต" in A.reroll("p", None)[A.cut_md]
    assert "ไม่มีงาน" in A.cancel_job("nothing-running")
    assert A.load_project("") == {A.editor: "", A.prompt_again: ""}
    assert "เลือก project" in A.save_editor("", "{}")[A.save_msg]
    first = next(A.run_job("render", "", "", None, 0, 0.5, 1.2, 2.0, ""))
    assert "เลือก project" in first[A.status]


def test_small_helpers():
    assert A._music_path(A.RANDOM_MUSIC) is None and A._music_path(None) is None
    assert str(A._music_path("a.mp3")).endswith("music/a.mp3")
    assert A.pick_video("", "final.mp4") is None
    assert A._settings(A.RANDOM_MUSIC, None, 0.5, 2, 2).music is None
    assert "เลือก project" in A.check_storyboard("", "{}")[A.save_msg]


def test_random_music_disables_start_and_waveform():
    view = A._music_view("p", A.RANDOM_MUSIC, 30)
    assert view[A.music_audio].value is None
    assert view[A.start_sl].interactive is False


@pytest.fixture
def tone_music(tmp_path, monkeypatch):
    import subprocess
    music = tmp_path / "music"
    music.mkdir()
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=f=440:d=90",
                    str(music / "tone.mp3")], check=True)
    monkeypatch.setattr(A.S, "MUSIC_DIR", music)
    return "tone.mp3"


def test_change_music_resets_start_and_sets_slider_max(projects, tone_music):
    view = A.change_music("", tone_music)
    slider = view[A.start_sl]
    assert slider.value == 0 and slider.maximum == pytest.approx(90, abs=0.5)
    assert view[A.music_audio].playback_position == 0
    assert view[A.wave_md].startswith("เริ่ม 0:00")


def test_move_start_updates_caption_and_clamps(projects, tone_music):
    out = A.move_start("", tone_music, 20)
    assert out[A.music_audio].playback_position == 20
    assert out[A.wave_md].startswith("เริ่ม 0:20 · ช่วงที่ใช้ 0:20–1:05")
    assert A._music_view("", tone_music, 999)[A.start_sl].value == pytest.approx(90, abs=0.5)
