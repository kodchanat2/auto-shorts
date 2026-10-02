import render_shorts as R
from gui import settings as S


def test_read_settings_uses_script_defaults_when_missing():
    s = S.read_settings({"scenes": []})
    assert s.music is None
    assert s.start_sec == R.BGM_START_SEC
    assert s.volume == R.BGM_VOLUME
    assert s.duck_ratio == R.BGM_DUCK_RATIO
    assert s.footage_speed == R.FOOTAGE_SPEED


def test_read_settings_prefers_storyboard_values():
    sb = {"bgm": {"file": "a.mp3", "start_sec": 12, "volume": 0.3, "duck_ratio": 3},
          "render": {"footage_speed": 1.5}}
    assert S.read_settings(sb) == S.RenderSettings("a.mp3", 12, 0.3, 3, 1.5)


def test_apply_settings_returns_new_dict_and_keeps_other_keys():
    sb = {"bgm": {"enabled": True}, "render": {"fps": 30}, "scenes": [1]}
    out = S.apply_settings(sb, S.RenderSettings("b.mp3", 5, 0.6, 2, 2.0))
    assert out is not sb and sb == {"bgm": {"enabled": True}, "render": {"fps": 30}, "scenes": [1]}
    assert out["bgm"] == {"enabled": True, "file": "b.mp3", "start_sec": 5, "volume": 0.6, "duck_ratio": 2}
    assert out["render"] == {"fps": 30, "footage_speed": 2.0}
    assert out["scenes"] == [1]


def test_list_music_filters_audio_files(tmp_path):
    for name in ["b.mp3", "a.wav", "README.txt", "c.m4a"]:
        (tmp_path / name).write_text("x")
    assert S.list_music(tmp_path) == ["a.wav", "b.mp3", "c.m4a"]


def test_read_voice_defaults_and_values():
    v = S.read_voice({})
    assert v.engine == "edge-tts" and v.rate_pct == 10 and v.style == ""
    sb = {"voice": {"engine": "gemini", "voice_id": "Rasalgethi", "style": "เร็ว", "rate": "+35%"}}
    assert S.read_voice(sb) == S.VoiceSettings("gemini", "Rasalgethi", "เร็ว", 35)


def test_apply_voice_keeps_other_voice_keys():
    sb = {"voice": {"pronunciations": {"AI": "เอไอ"}, "line_gap_sec": 0.05}}
    out = S.apply_voice(sb, S.VoiceSettings("gemini", "Puck", "ช้า", -5))
    assert out["voice"] == {"pronunciations": {"AI": "เอไอ"}, "line_gap_sec": 0.05,
                            "engine": "gemini", "voice_id": "Puck", "style": "ช้า", "rate": "-5%"}
    assert sb == {"voice": {"pronunciations": {"AI": "เอไอ"}, "line_gap_sec": 0.05}}


def test_voices_for_engine():
    import tts_gemini as G
    assert S.voices_for("edge-tts") == S.EDGE_VOICES
    assert S.voices_for("gemini") == G.GEMINI_VOICES and G.DEFAULT_VOICE in G.GEMINI_VOICES
    assert S.default_voice("gemini") == G.DEFAULT_VOICE
    assert S.default_voice("edge-tts") == "th-TH-NiwatNeural"
