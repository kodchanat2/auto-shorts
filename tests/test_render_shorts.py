import json

import pytest

import render_shorts as R


def make_cut(**over):
    base = dict(scene_id="S1", cut_id="S1C1", variant=0, query="man typing", fallbacks=[],
                shot_type="close_up", intent="", pinned_id=None)
    return R.CutPlan(**{**base, **over})


def fake_video(vid, duration=20):
    return {"id": vid, "duration": duration, "width": 1080, "height": 1920,
            "video_files": [{"id": vid * 10, "file_type": "video/mp4", "width": 1080,
                             "height": 1920, "link": f"https://example/{vid}.mp4"}]}


class FakePexels(R.Pexels):
    def __init__(self, cache, results):
        super().__init__("key", cache, refresh=False)
        self.results = results

    def search(self, query, orientation):
        return self.results if orientation == "portrait" else []


@pytest.fixture(autouse=True)
def reset_globals():
    R.WARNINGS.clear()
    R.PROGRESS = False
    yield
    R.PROGRESS = False


def test_progress_is_silent_by_default(capsys):
    R.progress(1, "Voiceover")
    assert capsys.readouterr().out == ""


def test_progress_prints_json_line_when_enabled(capsys):
    R.PROGRESS = True
    R.progress(4, "Pexels footage", 3, 17)
    line = capsys.readouterr().out.strip()
    assert line.startswith(R.PROGRESS_PREFIX)
    event = json.loads(line[len(R.PROGRESS_PREFIX):])
    assert event == {"stage": 4, "stages": 5, "label": "Pexels footage", "done": 3, "total": 17}


def test_choose_takes_first_suitable_clip(tmp_path):
    px = FakePexels(tmp_path, [fake_video(1), fake_video(2)])
    cut = make_cut()
    px.choose(cut, need_s=2.0, W=1080, H=1920)
    assert cut.video["id"] == 1


def test_choose_skips_excluded_ids(tmp_path):
    px = FakePexels(tmp_path, [fake_video(1), fake_video(2), fake_video(3)])
    cut = make_cut(excluded=(1, 2))
    px.choose(cut, need_s=2.0, W=1080, H=1920)
    assert cut.video["id"] == 3


def test_excluded_ids_are_not_reused_as_last_resort(tmp_path):
    px = FakePexels(tmp_path, [fake_video(1)])
    cut = make_cut(excluded=(1,))
    with pytest.raises(SystemExit):
        px.choose(cut, need_s=2.0, W=1080, H=1920)


def test_allocate_cuts_passes_exclusions_to_every_variant():
    scene = R.ScenePlan("S1", "HOOK", [], [
        {"cut_id": "S1C1", "duration_hint_sec": 2.0, "shot_type": "close_up",
         "pexels_query": "man typing", "exclude_video_ids": [5, 6]},
    ])
    scene.frames = 30 * 6  # 6 s of audio forces the single cut to split into variants
    cuts = R.allocate_cuts(scene, fps=30, min_s=1.5, max_s=3.0)
    assert len(cuts) >= 2
    assert all(c.excluded == (5, 6) for c in cuts)


def test_schema_accepts_exclude_video_ids():
    import jsonschema
    schema = json.loads((R.SCRIPT_DIR / "storyboard.schema.json").read_text(encoding="utf-8"))
    cut_schema = schema["$defs"]["cut"]
    cut = {"cut_id": "S1C1", "duration_hint_sec": 2, "shot_type": "wide",
           "pexels_query": "city at night", "exclude_video_ids": [123, 456]}
    jsonschema.validate(cut, cut_schema)


def _voice(**over):
    return {**R.DEFAULTS["voice"], "engine": "gemini", "voice_id": "Puck", "style": "เร็ว", **over}


def test_gemini_cache_key_differs_from_edge_and_by_style(tmp_path):
    edge = {**R.DEFAULTS["voice"], "voice_id": "th-TH-NiwatNeural"}
    a, _ = R._line_audio_paths("สวัสดี", edge, tmp_path)
    b, _ = R._line_audio_paths("สวัสดี", _voice(), tmp_path)
    c, _ = R._line_audio_paths("สวัสดี", _voice(style="ช้า"), tmp_path)
    assert a.suffix == ".mp3" and b.suffix == ".wav"
    assert len({a.name, b.name, c.name}) == 3


def test_synthesize_lines_with_gemini_uses_client_and_caches(tmp_path, monkeypatch):
    import tts_gemini as G
    calls = []

    def fake_synth(jobs, voice, style, rate, client, **kw):
        for text, out, emotion in jobs:
            calls.append((text, voice, style, rate))
            out.write_bytes(b"RIFF" + b"\0" * 2000)
        return ["mismatch warning"]
    monkeypatch.setattr(G, "make_client", lambda key: object())
    monkeypatch.setattr(G, "synthesize_all", fake_synth)
    lines = [R.Line("หนึ่ง", "หนึ่ง"), R.Line("สอง", "สอง")]
    R.synthesize_lines(lines, _voice(), tmp_path)
    assert sorted(c[0] for c in calls) == ["สอง", "หนึ่ง"]
    assert all(c[1:] == ("Puck", "เร็ว", "+0%") for c in calls)  # rate applied later at decode
    assert all(ln.words == [] and ln.mp3.suffix == ".wav" for ln in lines)
    assert any("proportional" in w for w in R.WARNINGS)
    assert "mismatch warning" in R.WARNINGS

    calls.clear()
    R.synthesize_lines([R.Line("หนึ่ง", "หนึ่ง")], _voice(), tmp_path)
    assert calls == []  # served from cache


def test_gemini_without_key_exits(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(SystemExit):
        R.synthesize_lines([R.Line("x", "x")], _voice(), tmp_path)


def test_gemini_cache_key_ignores_rate(tmp_path):
    a, _ = R._line_audio_paths("สวัสดี", _voice(rate="+10%"), tmp_path)
    b, _ = R._line_audio_paths("สวัสดี", _voice(rate="+40%"), tmp_path)
    assert a == b


def test_decode_pcm_applies_tempo(tmp_path):
    import subprocess
    src = tmp_path / "t.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=f=440:d=2", str(src)], check=True)
    normal = R.decode_pcm(src, tmp_path / "a.wav")
    fast = R.decode_pcm(src, tmp_path / "b.wav", tempo=2.0)
    assert len(fast) == pytest.approx(len(normal) / 2, rel=0.02)


def test_gemini_cache_key_includes_emotion_but_edge_ignores_it(tmp_path):
    g1, _ = R._line_audio_paths("สวัสดี", _voice(), tmp_path, "tense")
    g2, _ = R._line_audio_paths("สวัสดี", _voice(), tmp_path, "warm")
    assert g1 != g2
    edge = {**R.DEFAULTS["voice"], "voice_id": "th-TH-NiwatNeural"}
    assert R._line_audio_paths("x", edge, tmp_path, "tense") == R._line_audio_paths("x", edge, tmp_path)


def test_synthesize_lines_passes_scene_emotion(tmp_path, monkeypatch):
    import tts_gemini as G
    seen = []

    def fake_synth(jobs, voice, style, rate, client, **kw):
        for text, out, emotion in jobs:
            seen.append((text, emotion))
            out.write_bytes(b"RIFF" + b"\0" * 2000)
        return []
    monkeypatch.setattr(G, "make_client", lambda key: object())
    monkeypatch.setattr(G, "synthesize_all", fake_synth)
    R.synthesize_lines([R.Line("ก", "ก", emotion="tense"), R.Line("ข", "ข")], _voice(), tmp_path)
    assert seen == [("ก", "tense"), ("ข", "")]
