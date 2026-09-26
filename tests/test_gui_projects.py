import json

import pytest

from gui import projects as P


def test_validate_name_rejects_bad_characters(tmp_path):
    assert P.validate_new_name("my clip", tmp_path)
    assert P.validate_new_name("../etc", tmp_path)
    assert P.validate_new_name("", tmp_path)


def test_validate_name_rejects_existing_project(tmp_path):
    (tmp_path / "taken").mkdir()
    assert "มีอยู่แล้ว" in P.validate_new_name("taken", tmp_path)


def test_validate_name_accepts_new_name(tmp_path):
    assert P.validate_new_name("my_clip-2", tmp_path) is None


def test_list_projects_only_returns_project_folders(tmp_path):
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "storyboard.json").write_text("{}")
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "brief.json").write_text("{}")
    (tmp_path / "empty").mkdir()
    (tmp_path / "file.txt").write_text("x")
    assert P.list_projects(tmp_path) == ["a", "b"]


def test_list_projects_handles_missing_root(tmp_path):
    assert P.list_projects(tmp_path / "missing") == []


def test_brief_round_trip(tmp_path):
    brief = P.Brief(topic="ทำไมแมวชอบกล่อง", tone="ตลก", duration=40)
    P.save_brief(tmp_path, brief)
    assert P.load_brief(tmp_path) == brief


def test_load_brief_returns_none_when_absent(tmp_path):
    assert P.load_brief(tmp_path) is None


@pytest.mark.parametrize("text", [
    '{"a": 1}',
    'นี่คือ storyboard:\n```json\n{"a": 1}\n```\nขอให้สนุก',
    '```\n{"a": 1}\n```',
    'ข้อความนำ {"a": 1} ข้อความท้าย',
])
def test_extract_json_finds_the_object(text):
    assert json.loads(P.extract_json(text)) == {"a": 1}


def test_extract_json_rejects_text_without_object():
    with pytest.raises(ValueError):
        P.extract_json("ไม่มี JSON เลย")


def test_extract_json_rejects_invalid_json():
    with pytest.raises(ValueError):
        P.extract_json('{"a": 1,}')


def test_video_filename_is_the_name_itself():
    assert P.video_filename("") == "final.mp4"
    assert P.video_filename("  ") == "final.mp4"
    assert P.video_filename("v2") == "v2.mp4"
    assert P.video_filename("cat-cut_B") == "cat-cut_B.mp4"
    with pytest.raises(ValueError):
        P.video_filename("v 2/../x")


def test_list_videos_lists_every_mp4_newest_first(tmp_path):
    import os
    old, new = tmp_path / "final.mp4", tmp_path / "v2.mp4"
    old.write_bytes(b"x")
    new.write_bytes(b"x")
    os.utime(old, (1, 1))
    (tmp_path / "notes.txt").write_text("x")
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / "clip.mp4").write_bytes(b"x")
    assert P.list_videos(tmp_path) == [new, old]
