import asyncio
import subprocess
from types import SimpleNamespace

import pytest

import tts_gemini as G

SR = 24000


def pcm_tone(seconds: float) -> bytes:
    return subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"sine=f=440:d={seconds}",
                           "-ar", str(SR), "-ac", "1", "-f", "s16le", "-"], capture_output=True, check=True).stdout


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout
    return float(out)


def msg(audio=None, heard=None, done=False):
    parts = [SimpleNamespace(inline_data=SimpleNamespace(data=audio))] if audio else []
    sc = SimpleNamespace(model_turn=SimpleNamespace(parts=parts) if parts else None,
                         output_transcription=SimpleNamespace(text=heard) if heard else None,
                         turn_complete=done)
    return SimpleNamespace(server_content=sc)


class FakeSession:
    """Replies to each turn with a tone; `script` maps turn index -> (seconds, transcript)."""

    def __init__(self, script, log):
        self.script, self.log, self.turn = script, log, -1

    async def send_client_content(self, turns, turn_complete):
        self.turn += 1
        self.log.append(turns["parts"][0]["text"])
        action = self.script(self.turn, turns["parts"][0]["text"])
        if isinstance(action, Exception):
            raise action
        self.pending = action

    async def receive(self):
        seconds, heard = self.pending
        audio = pcm_tone(seconds)
        half = len(audio) // 2 // 2 * 2
        yield msg(audio=audio[:half])
        yield SimpleNamespace(server_content=None)
        yield msg(audio=audio[half:], heard=heard)
        yield msg(done=True)


class FakeClient:
    def __init__(self, script):
        self.log, self.configs, self.connects = [], [], 0
        client = self

        class Conn:
            def __init__(self, model, config):
                client.connects += 1
                client.configs.append((model, config))

            async def __aenter__(self):
                return FakeSession(script, client.log)

            async def __aexit__(self, *exc):
                return False
        self.aio = SimpleNamespace(live=SimpleNamespace(connect=lambda model, config: Conn(model, config)))


def echo(seconds=1.0):
    return lambda i, text: (seconds, text)


def test_tempo_factor():
    assert G.tempo_factor("+10%") == pytest.approx(1.10)
    assert G.tempo_factor("-20%") == pytest.approx(0.80)


def test_resolve_voice_replaces_edge_voice_names():
    assert G.resolve_voice("Puck") == "Puck"
    assert G.resolve_voice("th-TH-NiwatNeural") == G.DEFAULT_VOICE
    assert G.resolve_voice("") == G.DEFAULT_VOICE


def test_live_config_carries_voice_style_and_transcription():
    cfg = G.live_config("Puck", "ตื่นเต้น", "tense")
    assert "tense" in cfg["system_instruction"]
    assert "อารมณ์" not in G.live_config("Puck", "", "")["system_instruction"]
    assert cfg["response_modalities"] == ["AUDIO"]
    assert cfg["speech_config"]["voice_config"]["prebuilt_voice_config"]["voice_name"] == "Puck"
    assert "ตื่นเต้น" in cfg["system_instruction"] and "ตรงตามบท" in cfg["system_instruction"]
    assert cfg["output_audio_transcription"] == {}


def test_similarity_ignores_spaces_and_punctuation():
    assert G.similarity("สวัสดี ครับ!", "สวัสดีครับ") == 1.0
    assert G.similarity("สวัสดีครับ", "ลาก่อน") < 0.5


def test_synthesize_all_writes_every_line_in_one_session(tmp_path):
    client = FakeClient(echo(2.0))
    jobs = [("หนึ่ง", tmp_path / "a.wav"), ("สอง", tmp_path / "b.wav")]
    warnings = G.synthesize_all(jobs, "Kore", "", "+25%", client)
    assert warnings == [] and client.connects == 1 and client.log == ["หนึ่ง", "สอง"]
    assert client.configs[0][0] == G.GEMINI_LIVE_MODEL
    for _, out in jobs:
        assert duration(out) == pytest.approx(2.0 / 1.25, abs=0.05)
    assert not list(tmp_path.glob("*.part*"))


def test_mismatched_reading_is_retried_then_warned(tmp_path):
    client = FakeClient(lambda i, text: (1.0, "ข้อความอื่นเลย"))
    warnings = G.synthesize_all([("หนึ่งสองสาม", tmp_path / "a.wav")], "Kore", "", "+0%", client)
    assert client.log == ["หนึ่งสองสาม", "หนึ่งสองสาม"]
    assert len(warnings) == 1 and "หนึ่งสองสาม" in warnings[0]
    assert (tmp_path / "a.wav").exists()


def test_missing_transcript_is_accepted(tmp_path):
    client = FakeClient(lambda i, text: (1.0, None))
    assert G.synthesize_all([("x", tmp_path / "a.wav")], "Kore", "", "+0%", client) == []
    assert client.log == ["x"]


def test_dropped_session_reconnects_and_skips_finished_lines(tmp_path):
    def script(i, text):
        if text == "สอง" and not getattr(script, "failed", False):
            script.failed = True
            return ConnectionError("socket closed")
        return (1.0, text)
    client = FakeClient(script)
    jobs = [("หนึ่ง", tmp_path / "a.wav"), ("สอง", tmp_path / "b.wav")]
    G.synthesize_all(jobs, "Kore", "", "+0%", client, sleep=lambda s: asyncio.sleep(0))
    assert client.connects == 2 and client.log == ["หนึ่ง", "สอง", "สอง"]
    assert all(out.exists() for _, out in jobs)


def test_quota_error_stops_immediately(tmp_path):
    client = FakeClient(lambda i, text: RuntimeError("429 RESOURCE_EXHAUSTED: quota exceeded"))
    with pytest.raises(G.QuotaExhausted):
        G.synthesize_all([("x", tmp_path / "a.wav")], "Kore", "", "+0%", client)
    assert client.connects == 1


def test_gives_up_after_repeated_failures(tmp_path):
    client = FakeClient(lambda i, text: ConnectionError("boom"))
    with pytest.raises(RuntimeError, match="Gemini Live failed"):
        G.synthesize_all([("x", tmp_path / "a.wav")], "Kore", "", "+0%", client,
                         sleep=lambda s: asyncio.sleep(0))
    assert client.connects == G.MAX_SESSIONS


def test_make_client_requires_key():
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        G.make_client("")


def test_one_session_per_emotion_group_in_order(tmp_path):
    client = FakeClient(echo(0.5))
    jobs = [("หนึ่ง", tmp_path / "a.wav", "tense"), ("สอง", tmp_path / "b.wav", "tense"),
            ("สาม", tmp_path / "c.wav", "warm")]
    G.synthesize_all(jobs, "Puck", "เร็ว", "+0%", client)
    assert client.connects == 2 and client.log == ["หนึ่ง", "สอง", "สาม"]
    systems = [cfg["system_instruction"] for _, cfg in client.configs]
    assert "tense" in systems[0] and "warm" in systems[1] and all("เร็ว" in s for s in systems)
    assert all(out.exists() for _, out, _ in jobs)


def test_default_voice_is_puck():
    assert G.DEFAULT_VOICE == "Puck"
