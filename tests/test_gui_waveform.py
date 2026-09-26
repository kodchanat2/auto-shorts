import subprocess

import pytest
from gui import waveform as W


@pytest.fixture
def tone(tmp_path):
    src = tmp_path / "tone.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=f=440:d=10", str(src)], check=True)
    return src


def test_duration_of_audio_file(tone):
    assert W.duration(tone) == pytest.approx(10.0, abs=0.1)


def test_duration_of_missing_file(tmp_path):
    assert W.duration(tmp_path / "missing.mp3") == 0.0


def test_used_span_is_clamped_to_track():
    assert W.used_span(20, 40, 144) == (20, 60)
    assert W.used_span(130, 40, 144) == (130, 144)
    assert W.used_span(-5, 40, 144) == (0, 40)


def test_caption_formats_minutes():
    assert W.caption(20, 39.2, 144) == "เริ่ม 0:20 · ช่วงที่ใช้ 0:20–0:59 จากทั้งหมด 2:24"
