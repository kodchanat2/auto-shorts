import json

import pytest

from gui import cuts as C

STORYBOARD = {"scenes": [
    {"scene_id": "S1", "cuts": [{"cut_id": "S1C1", "pexels_query": "a"},
                                {"cut_id": "S1C2", "pexels_query": "b", "pexels_video_id": 9}]},
]}


def write_timeline(project, cuts):
    (project / "timeline.json").write_text(json.dumps({"scenes": [{"scene_id": "S1", "cuts": cuts}]}))


def test_load_cuts_reads_timeline_and_finds_local_footage(tmp_path):
    footage = tmp_path / "cache" / "pexels" / "footage"
    footage.mkdir(parents=True)
    (footage / "pexels_111_1110.mp4").write_bytes(b"x")
    write_timeline(tmp_path, [
        {"cut_id": "S1C1", "variant": 0, "pexels_video_id": 111, "pexels_url": "u1",
         "query_used": "a", "source_start_sec": 1.5},
        {"cut_id": "S1C1", "variant": 1, "pexels_video_id": 222, "pexels_url": "u2",
         "query_used": "a", "source_start_sec": 0.0},
    ])
    cuts = C.load_cuts(tmp_path)
    assert [c.label for c in cuts] == ["S1C1", "S1C1′"]
    assert cuts[0].local == footage / "pexels_111_1110.mp4"
    assert cuts[1].local is None
    assert cuts[0].video_id == 111 and cuts[0].src_start == 1.5


def test_load_cuts_without_rendered_timeline(tmp_path):
    assert C.load_cuts(tmp_path) == []
    (tmp_path / "timeline.json").write_text(json.dumps({"scenes": [{"scene_id": "S1", "lines": []}]}))
    assert C.load_cuts(tmp_path) == []  # --tts-only timeline has no clip ids yet


def test_reroll_excludes_current_clip_and_drops_pin():
    out = C.reroll(STORYBOARD, "S1C2", current_id=9)
    cut = out["scenes"][0]["cuts"][1]
    assert cut["exclude_video_ids"] == [9]
    assert "pexels_video_id" not in cut
    assert "exclude_video_ids" not in STORYBOARD["scenes"][0]["cuts"][1]  # input untouched


def test_reroll_twice_accumulates_without_duplicates():
    once = C.reroll(STORYBOARD, "S1C1", current_id=5)
    twice = C.reroll(once, "S1C1", current_id=6)
    again = C.reroll(twice, "S1C1", current_id=6)
    assert again["scenes"][0]["cuts"][0]["exclude_video_ids"] == [5, 6]


def test_unknown_cut_raises():
    with pytest.raises(KeyError):
        C.reroll(STORYBOARD, "S9C9", 1)


def test_thumbnail_extracts_cropped_frame_and_caches(tmp_path):
    import subprocess
    src = tmp_path / "clip.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=10",
                    "-t", "3", str(src)], check=True)
    cut = C.CutInfo("S1C1", 0, 42, "", "q", 0.5, src)
    thumb = C.thumbnail(cut, tmp_path, speed=2.0)
    assert thumb and thumb.exists()
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height",
                            "-of", "csv=p=0", str(thumb)], capture_output=True, text=True).stdout.strip()
    assert probe == f"{C.THUMB_W},{C.THUMB_H}"
    assert C.thumbnail(cut, tmp_path, speed=2.0) == thumb  # cached


def test_thumbnail_without_local_file():
    assert C.thumbnail(C.CutInfo("S1C1", 0, 1, "", "q", 0, None), None, 1.0) is None
